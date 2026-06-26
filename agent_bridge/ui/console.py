from __future__ import annotations

import json
import re
import time
from datetime import datetime
from textwrap import shorten
from typing import Callable

from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Header, RichLog, Static, TextArea

from ..config import Settings
from ..services.rollback import RollbackError
from ..services.git_context import get_git_diff
from ..services.history import HistoryService
from ..services.runner import run_shell_command, terminate_active_processes
from ..services.workflow import Workflow, WorkflowError
from .translations import DEFAULT_LANGUAGE, Language, SUPPORTED_LANGUAGES, translate


class ConsoleApp(App[None], inherit_css=False):
    TITLE = "Agent Bridge"
    SUB_TITLE = "Builder -> Reviewer workflow"

    CSS = """
    Screen {
        background: #0d1117;
        color: #c9d1d9;
        layout: vertical;
    }

    #status_bar {
        height: 7;
        layout: horizontal;
        padding: 0 1;
    }

    #main {
        height: 1fr;
        layout: horizontal;
        padding: 0 1;
    }

    #sidebar {
        width: 34%;
        min-width: 34;
        layout: vertical;
        margin-right: 1;
    }

    #workspace {
        width: 1fr;
        layout: vertical;
    }

    .panel {
        border: solid #30363d;
        background: #111820;
        color: #c9d1d9;
        padding: 0 1;
        margin-bottom: 1;
    }

    .stat-card {
        height: 6;
        border: solid #30363d;
        background: #111820;
        color: #c9d1d9;
        padding: 0 1;
        margin-right: 1;
    }

    #status_card {
        width: 2fr;
    }

    #builder_chip, #reviewer_chip {
        width: 1fr;
    }

    #config_card {
        width: 2fr;
        margin-right: 0;
    }

    #task_panel {
        height: 12;
    }

    #history_panel {
        height: 1fr;
    }

    #live_panel {
        height: 1fr;
    }

    #menu_panel {
        height: 5;
        padding: 0 1;
        border: solid #30363d;
        background: #0f141b;
    }

    #menu_hint,
    #menu_commands_1,
    #menu_commands_2 {
        color: #9fb3c8;
        height: 1;
    }

    #task_editor {
        height: 1fr;
        margin-top: 1;
    }

    #live_log,
    #history_log {
        height: 1fr;
        margin-top: 0;
    }

    """

    BINDINGS = [
        Binding("f2", "save_task", "Save", show=True),
        Binding("ctrl+n", "new_task", "New task", show=False),
        Binding("f5", "run_next", "Go", show=False),
        Binding("f6", "stop_running", "Stop", show=False),
        Binding("ctrl+b", "run_build", "Build", show=False),
        Binding("ctrl+r", "run_review", "Review", show=False),
        Binding("ctrl+d", "show_diff", "Diff", show=False),
        Binding("ctrl+z", "rollback_changes", "Rollback", show=False),
        Binding("ctrl+t", "run_tests", "Tests", show=False),
        Binding("ctrl+l", "clear_activity", "Clear", show=False),
        Binding("ctrl+g", "toggle_language", "Language", show=True),
        Binding("ctrl+q", "quit", "Exit", show=True),
    ]

    def __init__(self, settings: Settings, workflow: Workflow, history: HistoryService):
        super().__init__()
        self.settings = settings
        self.workflow = workflow
        self.history = history
        self.language: Language = DEFAULT_LANGUAGE
        self._ui_ready = False
        self._last_message = self._t("status_waiting")
        self._builder_status = "waiting"
        self._reviewer_status = "waiting"
        self._active_role = "-"
        self._active_started_at: datetime | None = None
        self._active_started_monotonic: float | None = None
        self._stop_requested = False
        self._usage = {
            "builder": {"runs": 0, "duration": 0.0, "stdout": 0, "stderr": 0, "tokens": 0, "tokens_known": False},
            "reviewer": {"runs": 0, "duration": 0.0, "stdout": 0, "stderr": 0, "tokens": 0, "tokens_known": False},
        }

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="status_bar"):
            yield Static(id="status_card", classes="stat-card")
            yield Static(id="builder_chip", classes="stat-card")
            yield Static(id="reviewer_chip", classes="stat-card")
            yield Static(id="config_card", classes="stat-card")
        with Container(id="main"):
            with Vertical(id="sidebar"):
                with Container(id="task_panel", classes="panel"):
                    yield Static(Text(self._t("task_title"), style="bold white"), id="task_title")
                    yield TextArea(
                        self.workflow.state.current_task or "",
                        id="task_editor",
                        placeholder=self._t("task_placeholder"),
                        soft_wrap=True,
                        tab_behavior="indent",
                        show_line_numbers=False,
                    )
                with Container(id="history_panel", classes="panel"):
                    yield Static(Text(self._t("history_title"), style="bold white"), id="history_title")
                    yield RichLog(id="history_log", markup=True, wrap=True, auto_scroll=True)
            with Vertical(id="workspace"):
                with Container(id="live_panel", classes="panel"):
                    yield Static(Text(self._t("live_output_title"), style="bold white"), id="live_title")
                    yield RichLog(id="live_log", markup=True, wrap=True, auto_scroll=True)
        with Container(id="menu_panel"):
            yield Static(
                Text(self._t("commands_title"), style="bold white"),
                id="menu_hint",
            )
            yield Static(self._render_menu_text(self._menu_commands_first_row()), id="menu_commands_1")
            yield Static(self._render_menu_text(self._menu_commands_second_row()), id="menu_commands_2")

    def on_mount(self) -> None:
        self.title = self._t("app_title")
        self.sub_title = self._t("app_subtitle")
        self._ui_ready = True
        self.set_interval(1.0, self._refresh_running_timer)
        self._refresh_ui()
        self._task_editor().focus()

    def action_save_task(self) -> None:
        try:
            self.save_task_text(self._task_editor().text)
            self._set_message(self._t("task_saved"))
        except WorkflowError as exc:
            self._set_error(str(exc))

    def action_new_task(self) -> None:
        self.workflow.state.current_task = None
        self.workflow.state.last_builder_result = None
        self.workflow.state.last_reviewer_result = None
        self.workflow.state.last_completed_role = None
        self.workflow.state.status = "waiting"
        self._builder_status = "waiting"
        self._reviewer_status = "waiting"
        self._active_role = "-"
        self._clear_active_run()
        self._task_editor().clear()
        self._set_message(self._t("new_task_title"))
        self._append_activity(self._t("new_task_title"), self._t("new_task_activity"), style="cyan")
        self._refresh_ui()
        self._task_editor().focus()

    def action_clear_task(self) -> None:
        self._task_editor().clear()
        self._set_message(self._t("task_cleared"))
        self._task_editor().focus()

    def action_run_next(self) -> None:
        self._stop_requested = False
        if not self._autosave_task_before_run():
            return
        next_action = self._next_run_action()
        if next_action == "reviewer":
            self._start_worker("reviewer", self._reviewer_worker, self._set_message)
            return
        if next_action == "builder_fix":
            self._start_worker("builder_fix", self._fix_worker, self._set_message, active_title="Builder fix")
            return
        if next_action == "done":
            self._set_message(self._t("run_queue_done"))
            return
        self._start_worker("builder", self._builder_worker, self._set_message)

    def action_run_build(self) -> None:
        self._stop_requested = False
        if not self._autosave_task_before_run():
            return
        if self._should_apply_review_feedback():
            self._start_worker("builder_fix", self._fix_worker, self._set_message, active_title="Builder fix")
            return
        self._start_worker("builder", self._builder_worker, self._set_message)

    def action_run_review(self) -> None:
        self._stop_requested = False
        self._start_worker("reviewer", self._reviewer_worker, self._set_message)

    def action_stop_running(self) -> None:
        stopped = terminate_active_processes()
        if not stopped:
            self._set_message(self._t("stop_no_active_run"))
            return
        self._stop_requested = True
        self.workflow.state.status = "stopped"
        if self._active_role.startswith("Reviewer"):
            self._reviewer_status = "stopped"
        elif self._active_role.startswith("Builder"):
            self._builder_status = "stopped"
        self._clear_active_run()
        self._set_message(self._t("stop_requested"))
        self._append_activity(self._t("command_stop"), self._t("stop_requested"), style="yellow")
        self._refresh_status_card()

    def action_show_diff(self) -> None:
        self._stop_requested = False
        self._start_worker("tools", self._git_diff_worker, self._set_message, active_title="Git diff")

    def action_run_tests(self) -> None:
        self._stop_requested = False
        self._start_worker("tools", self._tests_worker, self._set_message, active_title=self._t("tests_title"))

    def action_rollback_changes(self) -> None:
        self._stop_requested = False
        self._start_worker("tools", self._rollback_worker, self._set_message, active_title=self._t("rollback_title"))

    def action_show_history(self) -> None:
        self._refresh_history_log()
        self._append_activity(self._t("history_title"), self._t("history_refreshed"), style="magenta")
        self._set_message(self._t("history_refreshed"))

    def action_clear_activity(self) -> None:
        self._activity_log().clear()
        self._append_activity(self._t("activity_title"), self._t("activity_cleared"), style="dim")
        self._set_message(self._t("activity_cleared"))

    def action_toggle_language(self) -> None:
        current_index = SUPPORTED_LANGUAGES.index(self.language)
        self.language = SUPPORTED_LANGUAGES[(current_index + 1) % len(SUPPORTED_LANGUAGES)]
        self.title = self._t("app_title")
        self.sub_title = self._t("app_subtitle")
        self._set_message(self._t("language_changed"))
        self._refresh_translated_text()
        self._refresh_ui()

    def action_quit(self) -> None:
        self.exit()

    def save_task_text(self, text: str) -> None:
        self.workflow.set_task(text)
        self._builder_status = "waiting"
        self._reviewer_status = "waiting"
        self._refresh_ui()
        self._refresh_history_log()
        self._append_activity(self._t("task_log_title"), f"{self._t('saved_task')}: {self._task_summary(text)}", style="green")

    def _autosave_task_before_run(self) -> bool:
        text = self._task_editor().text
        task = text.strip()
        if task == (self.workflow.state.current_task or ""):
            return True
        try:
            self.save_task_text(text)
        except WorkflowError as exc:
            self._set_error(str(exc))
            return False
        return True

    def _start_worker(
        self,
        group: str,
        worker: Callable[[], None],
        status_message: Callable[[str], None],
        active_title: str | None = None,
    ) -> None:
        status_message(self._t("run_started"))
        self._set_running_state(group, active_title=active_title)
        self.run_worker(worker, name=group, group=group, exclusive=group.startswith("builder") or group == "reviewer", thread=True, exit_on_error=False)

    def _builder_worker(self) -> None:
        try:
            self.call_from_thread(self._prepare_live_output, "Builder")
            result = self.workflow.run_builder(stream_callback=self._builder_stream)
        except Exception as exc:
            self.call_from_thread(self._handle_worker_error, "Builder", exc)
            return
        self.call_from_thread(self._handle_builder_result, result)

    def _reviewer_worker(self) -> None:
        try:
            self.call_from_thread(self._prepare_live_output, "Reviewer")
            result = self.workflow.send_builder_to_reviewer(stream_callback=self._reviewer_stream)
        except Exception as exc:
            self.call_from_thread(self._handle_worker_error, "Reviewer", exc)
            return
        self.call_from_thread(self._handle_reviewer_result, result)

    def _fix_worker(self) -> None:
        try:
            self.call_from_thread(self._prepare_live_output, "Builder fix")
            result = self.workflow.send_review_back_to_builder(stream_callback=self._builder_stream)
        except Exception as exc:
            self.call_from_thread(self._handle_worker_error, "Builder fix", exc)
            return
        self.call_from_thread(self._handle_builder_result, result, True)

    def _builder_stream(self, stream_name: str, line: str) -> None:
        self.call_from_thread(self._append_live_output, "Builder", stream_name, line)

    def _reviewer_stream(self, stream_name: str, line: str) -> None:
        self.call_from_thread(self._append_live_output, "Reviewer", stream_name, line)

    def _git_diff_worker(self) -> None:
        try:
            diff = get_git_diff(self.settings.project_dir)
        except Exception as exc:
            self.call_from_thread(self._handle_worker_error, "Git diff", exc)
            return
        self.call_from_thread(self._handle_diff_result, diff)

    def _tests_worker(self) -> None:
        if not self.settings.test_command.strip():
            self.call_from_thread(self._handle_worker_error, self._t("tests_title"), WorkflowError(self._t("tests_not_configured")))
            return
        result = run_shell_command(self.settings.test_command, cwd=self.settings.project_dir, timeout=self.settings.agent_timeout)
        self.call_from_thread(self._handle_tests_result, result)

    def _rollback_worker(self) -> None:
        try:
            result = self.workflow.rollback_last_changes()
        except (RollbackError, WorkflowError) as exc:
            self.call_from_thread(self._handle_worker_error, self._t("rollback_title"), exc)
            return
        except Exception as exc:
            self.call_from_thread(self._handle_worker_error, self._t("rollback_title"), exc)
            return
        self.call_from_thread(self._handle_rollback_result, result)

    def _handle_builder_result(self, result, is_fix: bool = False) -> None:
        title = "Builder fix" if is_fix else "Builder"
        if self._handle_stopped_result(title):
            return
        self._builder_status = "success" if result.returncode == 0 else "error"
        self._clear_active_run()
        self._set_message(self._t("builder_done"))
        self._update_usage("builder", result)
        self._refresh_history_log()
        self._append_activity(title, self._result_summary(result), style="green" if result.returncode == 0 else "red")
        self._update_final_result(title, result, self._builder_status)
        self._refresh_status_card()

    def _handle_reviewer_result(self, result) -> None:
        if self._handle_stopped_result("Reviewer"):
            return
        self._reviewer_status = "success" if result.returncode == 0 else "error"
        self._clear_active_run()
        self._set_message(self._t("reviewer_done"))
        self._update_usage("reviewer", result)
        self._refresh_history_log()
        self._append_activity("Reviewer", self._result_summary(result), style="green" if result.returncode == 0 else "red")
        self._update_final_result("Reviewer", result, self._reviewer_status)
        self._refresh_status_card()

    def _handle_diff_result(self, diff: str) -> None:
        self.workflow.state.status = "success"
        self._clear_active_run()
        self._set_message(self._t("diff_ready"))
        self._activity_log().write(Text("Git diff", style="bold magenta"))
        self._activity_log().write(Syntax(diff or self._t("empty"), "diff", word_wrap=False))
        self._refresh_history_log()
        self._refresh_status_card()

    def _handle_tests_result(self, result) -> None:
        if self._handle_stopped_result(self._t("tests_title")):
            return
        self.workflow.state.status = "success" if result.returncode == 0 else "error"
        self._clear_active_run()
        self._set_message(self._t("tests_done"))
        self.workflow.history.append(
            "test_result",
            {
                "command": result.command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "duration_sec": result.duration_sec,
            },
        )
        self._activity_log().write(Text(self._t("tests_title"), style="bold yellow"))
        self._activity_log().write(self._render_command_result(result.command, result.stdout, result.stderr, result.returncode))
        self._refresh_history_log()
        self._refresh_status_card()

    def _handle_rollback_result(self, result) -> None:
        if self._handle_stopped_result(self._t("rollback_title")):
            return
        self.workflow.state.status = "success"
        self._clear_active_run()
        self._set_message(self._t("rollback_done").format(count=result.changed_count))
        self._activity_log().write(Text(self._t("rollback_title"), style="bold yellow"))
        self._activity_log().write(self._render_rollback_result(result))
        self._refresh_history_log()
        self._refresh_status_card()

    def _handle_worker_error(self, title: str, exc: Exception) -> None:
        message = str(exc)
        self.workflow.state.status = "error"
        if title.startswith("Builder"):
            self._builder_status = "error"
        elif title == "Reviewer":
            self._reviewer_status = "error"
        self._clear_active_run()
        self._append_activity(title, message, style="red")
        self._set_error(f"{title}: {message}")
        self._refresh_status_card()

    def _refresh_ui(self) -> None:
        if not self._ui_ready:
            return
        self._refresh_status_card()
        self._refresh_config_card()
        self._update_initial_result_widgets()
        self._refresh_history_log()
        self._set_task_editor(self.workflow.state.current_task or "")

    def _refresh_status_card(self) -> None:
        if not self._ui_ready:
            return
        self._status_card().update(self._render_status_card())
        self._builder_chip().update(
            self._render_agent_chip("Builder", self.settings.builder_agent, self._builder_status, self._usage["builder"])
        )
        self._reviewer_chip().update(
            self._render_agent_chip("Reviewer", self.settings.reviewer_agent, self._reviewer_status, self._usage["reviewer"])
        )

    def _refresh_config_card(self) -> None:
        if not self._ui_ready:
            return
        self._config_card().update(self._render_config_card())

    def _refresh_history_log(self) -> None:
        if not self._ui_ready:
            return
        log = self._history_log_or_none()
        if log is None:
            return
        log.clear()
        for record in self.history.read_current_session():
            log.write(self._render_history_entry(record))

    def _update_initial_result_widgets(self) -> None:
        if not self._ui_ready:
            return
        result = self.workflow.state.last_reviewer_result or self.workflow.state.last_builder_result
        if result is None:
            return
        self._live_log().clear()
        title = "Reviewer" if result.role == "reviewer" else "Builder"
        status = "success" if result.returncode == 0 else "error"
        self._update_final_result(title, result, status)

    def _update_final_result(self, title: str, result, status: str) -> None:
        if not self._ui_ready:
            return
        self._append_final_result(title, result, status)

    def _render_status_card(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, no_wrap=True)
        table.add_column(ratio=2)
        table.add_row(Text(self._t("status"), style="grey70"), self._status_badge(self.workflow.state.status))
        table.add_row(Text(self._t("active_run"), style="grey70"), Text(self._active_run_summary(), style="white"))
        table.add_row(Text(self._t("project"), style="grey70"), Text(self._short_path(self.settings.project_dir), style="white"))
        table.add_row(Text(self._t("message"), style="grey70"), Text(self._short_text(self._last_message, 64), style="white"))
        return table

    def _render_config_card(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, no_wrap=True)
        table.add_column(ratio=2)
        table.add_row(Text(self._t("config_pair"), style="grey70"), Text(f"{self.settings.builder_agent}/{self.settings.reviewer_agent}", style="white"))
        table.add_row(Text(self._t("config_timeout"), style="grey70"), Text(f"{self.settings.agent_timeout}s", style="white"))
        table.add_row(Text(self._t("config_tests"), style="grey70"), Text(self._short_text(self.settings.test_command or self._t("not_set"), 48), style="white"))
        table.add_row(Text(self._t("config_language"), style="grey70"), Text(self._t(f"language_{self.language}"), style="white"))
        return table

    def _render_agent_chip(self, title: str, engine: str, status: str, usage: dict[str, object]) -> Text:
        text = Text()
        text.append(f"{title}\n", style="bold white")
        text.append(self._status_label(status), style=self._status_text_style(status))
        text.append(f"\n{self._format_usage_summary(usage)}", style="grey70")
        return text

    def _format_usage_summary(self, usage: dict[str, object]) -> str:
        tokens = str(usage["tokens"]) if usage["tokens_known"] else self._t("usage_tokens_unknown")
        return self._t("usage_runs").format(
            runs=usage["runs"],
            duration=usage["duration"],
            tokens=tokens,
        )

    def _render_agent_meta(self, title: str, engine: str, result, status: str = "waiting") -> Table:
        returncode_text = "-"
        duration_text = "-"
        if result is not None:
            status = "success" if result.returncode == 0 else "error"
            returncode_text = str(result.returncode)
            duration_text = f"{result.duration_sec:.1f}s"

        meta = Table.grid(expand=True)
        meta.add_column(ratio=1, no_wrap=True)
        meta.add_column(ratio=1, justify="right")
        meta.add_row(Text(title, style="bold white"), self._status_badge(status))
        meta.add_row(Text(engine, style="grey70"), Text(f"rc {returncode_text} / {duration_text}", style="grey70"))
        return meta

    @staticmethod
    def _role_style(title: str) -> str:
        if title.startswith("Reviewer"):
            return "magenta"
        if title.startswith("Builder"):
            return "cyan"
        return "blue"

    def _prepare_live_output(self, title: str) -> None:
        if not self._ui_ready:
            return
        self._active_role = title
        log = self._live_log()
        log.clear()
        log.write(
            Panel(
                Text(f"{title} · {self._agent_engine_for_title(title)}", style=f"bold {self._role_style(title)}"),
                title=self._t("prompt_and_process"),
                border_style=self._role_style(title),
                padding=(0, 1),
            )
        )
        self._append_activity(title, self._t("process_started"), style="yellow")

    def _append_final_result(self, title: str, result, status: str) -> None:
        log = self._live_log()
        log.write(Text(""))
        stdout = result.text.strip()
        border_style = self._role_style(title) if status == "success" else "red"
        result_body = Markdown(stdout or self._t("empty_output")) if stdout else Text(self._t("empty"), style="grey70")
        log.write(
            Panel(
                result_body,
                title=f"{title} · {self._t('final_result_title')}",
                border_style=border_style,
                padding=(0, 1),
            )
        )

    def _append_live_output(self, title: str, stream_name: str, line: str) -> None:
        if not self._ui_ready or not line:
            return
        for output_line in line.splitlines() or [line]:
            style = self._stream_line_style(stream_name, output_line)
            self._live_log().write(self._render_stream_line(title, stream_name, output_line, style))
            if style == "red":
                self._append_activity(title, self._short_text(output_line, 140), style="red")

    def _update_usage(self, role: str, result) -> None:
        usage = self._usage[role]
        usage["runs"] += 1
        usage["duration"] += result.duration_sec
        usage["stdout"] += len(result.stdout)
        usage["stderr"] += len(result.stderr)
        tokens = self._extract_token_usage(result.stdout + "\n" + result.stderr)
        if tokens is not None:
            usage["tokens"] += tokens
            usage["tokens_known"] = True
        self._refresh_status_card()

    def _render_menu_text(self, commands: list[tuple[str, str]]) -> Text:
        text = Text()
        for index, (key, label) in enumerate(commands):
            if index:
                text.append("  |  ", style="grey50")
            text.append(key, style="bold cyan")
            text.append(f" {label}", style="white")
        return text

    def _menu_commands_first_row(self) -> list[tuple[str, str]]:
        return [
            ("F2", self._t("save")),
            ("^N", self._t("new")),
            ("F5", self._t("command_go")),
            ("F6", self._t("command_stop")),
            ("^B", self._t("command_build")),
            ("^R", self._t("command_review")),
        ]

    def _menu_commands_second_row(self) -> list[tuple[str, str]]:
        return [
            ("^D", self._t("command_diff")),
            ("^Z", self._t("command_rollback")),
            ("^T", self._t("command_tests")),
            ("^L", self._t("clear")),
            ("^G", self._t("config_language")),
            ("^Q", self._t("exit")),
        ]

    def _render_history_entry(self, record: dict[str, object]) -> Text:
        event_type = str(record.get("type", "event"))
        timestamp = str(record.get("timestamp", ""))[-8:]
        summary = self._history_summary(record)
        style = {
            "task_created": "cyan",
            "builder_result": "green",
            "reviewer_result": "green",
            "fix_result": "green",
            "test_result": "yellow",
            "rollback_snapshot": "dim",
            "rollback_snapshot_error": "red",
            "rollback_result": "yellow",
            "approved": "green",
            "error": "red",
        }.get(event_type, "white")
        label = {
            "task_created": "task",
            "builder_result": "build",
            "reviewer_result": "review",
            "fix_result": "fix",
            "test_result": "test",
            "rollback_snapshot": "snap",
            "rollback_snapshot_error": "snaperr",
            "rollback_result": "undo",
            "approved": "ok",
            "error": "error",
        }.get(event_type, event_type)
        return Text(f"{timestamp} | {label:<7} | {summary}", style=style)

    def _append_activity(self, title: str, message: str, style: str = "white") -> None:
        if not self._ui_ready:
            return
        self._activity_log().write(Text(f"{title:<10} {self._short_text(message, 140)}", style=style))

    def _set_error(self, message: str) -> None:
        self._last_message = message
        self.workflow.history.append("error", {"message": message})
        self._refresh_status_card()
        if self._ui_ready:
            self._activity_log().write(Text(self._short_text(message, 160), style="red"))
            self._refresh_history_log()

    def _set_message(self, message: str) -> None:
        self._last_message = message
        self._refresh_status_card()

    def _set_running_state(self, action: str, active_title: str | None = None) -> None:
        if action.startswith("builder"):
            self._builder_status = "running"
            self.workflow.state.status = "running"
            self._set_active_run(active_title or "Builder")
        elif action == "reviewer":
            self._reviewer_status = "running"
            self.workflow.state.status = "running"
            self._set_active_run(active_title or "Reviewer")
        elif action == "tools":
            self.workflow.state.status = "running"
            self._set_active_run(active_title or self._t("command_run"))
        self._set_message(self._t("run_started"))
        self._refresh_status_card()

    def _handle_stopped_result(self, title: str) -> bool:
        if not self._stop_requested:
            return False
        self.workflow.state.status = "stopped"
        if title.startswith("Builder"):
            self._builder_status = "stopped"
        elif title == "Reviewer":
            self._reviewer_status = "stopped"
        self._stop_requested = False
        self._clear_active_run()
        self._set_message(self._t("run_stopped"))
        self._append_activity(title, self._t("run_stopped"), style="yellow")
        self._refresh_status_card()
        return True

    def _set_active_run(self, role: str) -> None:
        self._active_role = role
        self._active_started_at = datetime.now()
        self._active_started_monotonic = time.monotonic()

    def _clear_active_run(self) -> None:
        self._active_started_at = None
        self._active_started_monotonic = None
        self._active_role = "-"

    def _refresh_running_timer(self) -> None:
        if self.workflow.state.status == "running" and self._active_started_monotonic is not None:
            self._refresh_status_card()

    def _active_run_summary(self) -> str:
        if self.workflow.state.status != "running" or self._active_started_at is None:
            return self._t("not_set")
        engine = self._agent_engine_for_title(self._active_role) if self._active_role.startswith(("Builder", "Reviewer")) else ""
        name = f"{self._active_role} ({engine})" if engine else self._active_role
        started = self._active_started_at.strftime("%H:%M:%S")
        elapsed = self._format_elapsed(self._active_elapsed_sec())
        return self._t("active_run_summary").format(name=name, started=started, elapsed=elapsed)

    def _active_elapsed_sec(self) -> float:
        if self._active_started_monotonic is None:
            return 0.0
        return max(0.0, time.monotonic() - self._active_started_monotonic)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _refresh_translated_text(self) -> None:
        if not self._ui_ready:
            return
        self.query_one("#task_title", Static).update(Text(self._t("task_title"), style="bold white"))
        try:
            self.query_one("#history_title", Static).update(Text(self._t("history_title"), style="bold white"))
        except NoMatches:
            pass
        self.query_one("#live_title", Static).update(Text(self._t("live_output_title"), style="bold white"))
        self.query_one("#menu_hint", Static).update(Text(self._t("commands_title"), style="bold white"))
        self.query_one("#menu_commands_1", Static).update(self._render_menu_text(self._menu_commands_first_row()))
        self.query_one("#menu_commands_2", Static).update(self._render_menu_text(self._menu_commands_second_row()))
        self._task_editor().placeholder = self._t("task_placeholder")

    def _task_editor(self) -> TextArea:
        return self.query_one("#task_editor", TextArea)

    def _status_card(self) -> Static:
        return self.query_one("#status_card", Static)

    def _builder_chip(self) -> Static:
        return self.query_one("#builder_chip", Static)

    def _reviewer_chip(self) -> Static:
        return self.query_one("#reviewer_chip", Static)

    def _config_card(self) -> Static:
        return self.query_one("#config_card", Static)

    def _live_log(self) -> RichLog:
        return self.query_one("#live_log", RichLog)

    def _activity_log(self) -> RichLog:
        return self._live_log()

    def _history_log(self) -> RichLog:
        return self.query_one("#history_log", RichLog)

    def _history_log_or_none(self) -> RichLog | None:
        try:
            return self._history_log()
        except NoMatches:
            return None

    def _set_task_editor(self, text: str) -> None:
        self._task_editor().load_text(text)

    def _status_badge(self, status: str) -> Text:
        styles = {
            "waiting": "black on bright_white",
            "running": "bold blue",
            "success": "black on green",
            "error": "white on red",
            "stopped": "black on bright_yellow",
        }
        return Text(f" {self._status_label(status)} ", style=styles.get(status, "white on black"))

    def _status_label(self, status: str) -> str:
        return self._t(f"status_{status}") if status in {"waiting", "running", "success", "error", "stopped"} else status.upper()

    @staticmethod
    def _status_text_style(status: str) -> str:
        return {
            "waiting": "grey70",
            "running": "blue",
            "success": "green",
            "error": "red",
            "stopped": "yellow",
        }.get(status, "white")

    @staticmethod
    def _stream_line_style(stream_name: str, line: str) -> str:
        if re.search(r"\b(error|failed|exception|traceback|fatal)\b", line, re.IGNORECASE):
            return "red"
        if re.search(r"\b(warn|warning|retry)\b", line, re.IGNORECASE):
            return "yellow"
        return "white"

    def _render_stream_line(self, title: str, stream_name: str, line: str, style: str | None = None):
        style = style or self._stream_line_style(stream_name, line)
        syntax = self._stream_line_syntax(line)
        if syntax is not None:
            return syntax
        content = Text.from_ansi(line.rstrip("\n"))
        if not content.spans:
            content.stylize(style)
        return content

    @staticmethod
    def _stream_line_syntax(line: str) -> Syntax | None:
        stripped = line.rstrip("\n")
        if not stripped.strip():
            return None
        if ConsoleApp._looks_like_diff_line(stripped):
            return Syntax(stripped, "diff", background_color="default", word_wrap=True)
        if ConsoleApp._looks_like_shell_command(stripped):
            command = re.sub(r"^\s*(?:[$>]\s*|(?:command|cmd)\s*:\s*)", "", stripped, flags=re.IGNORECASE)
            return Syntax(command, "bash", background_color="default", word_wrap=True)
        if ConsoleApp._looks_like_json(stripped):
            return Syntax(stripped, "json", background_color="default", word_wrap=True)
        return None

    @staticmethod
    def _looks_like_diff_line(line: str) -> bool:
        stripped = line.lstrip()
        return (
            stripped.startswith(("diff --git ", "index ", "@@ ", "+++ ", "--- "))
            or (stripped.startswith(("+", "-")) and not stripped.startswith(("+++", "---")))
        )

    @staticmethod
    def _looks_like_shell_command(line: str) -> bool:
        stripped = line.strip()
        return bool(
            re.match(r"^(?:[$>]\s+|(?:command|cmd)\s*:\s*)\S+", stripped, re.IGNORECASE)
            or re.match(r"^(?:npm|pnpm|yarn|python|python3|pytest|git|docker|cargo|go|php|composer)\s+\S+", stripped)
        )

    @staticmethod
    def _looks_like_json(line: str) -> bool:
        stripped = line.strip()
        return (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]"))

    def _agent_engine_for_title(self, title: str) -> str:
        if title.startswith("Reviewer"):
            return self.settings.reviewer_agent
        return self.settings.builder_agent

    def _should_apply_review_feedback(self) -> bool:
        if self.workflow.state.last_completed_role != "reviewer":
            return False
        review = self.workflow.state.last_reviewer_result
        if review is None:
            return False
        return review.text.strip().upper() != "OK"

    def _next_run_action(self) -> str:
        last_completed_role = self.workflow.state.last_completed_role
        if self.workflow.state.last_builder_result is None or last_completed_role is None:
            return "builder"
        if last_completed_role == "builder":
            return "reviewer"
        if last_completed_role == "reviewer" and self._should_apply_review_feedback():
            return "builder_fix"
        return "done"

    @classmethod
    def _extract_token_usage(cls, text: str) -> int | None:
        totals: list[int] = []
        totals.extend(cls._extract_json_token_usage(text))
        text_lines = [
            line
            for line in text.splitlines()
            if not (line.strip().startswith("{") and line.strip().endswith("}"))
        ]
        text_without_json = "\n".join(text_lines)
        totals.extend(cls._extract_text_token_usage(text_without_json))

        return sum(totals) if totals else None

    @staticmethod
    def _extract_text_token_usage(text: str) -> list[int]:
        total_context = {"total", "used", "usage", "spent", "consumed"}
        component_context = {"input", "prompt", "output", "completion"}
        token_context = "|".join((*total_context, *component_context))
        context_before_tokens = re.compile(
            rf"\b(?P<context>{token_context})[\s:.-]{{0,16}}(?:tokens?|tok)\D{{0,12}}(?P<tokens>[\d,]+)\b",
            re.IGNORECASE,
        )
        context_before_number = re.compile(
            rf"\b(?P<context>{token_context})[\s:.-]{{0,16}}(?P<tokens>[\d,]+)\s*(?:tokens?|tok)\b",
            re.IGNORECASE,
        )
        tokens_before_context = re.compile(
            rf"\b(?P<tokens>[\d,]+)\s+(?:tokens?|tok)\b[\w\s./-]{{0,32}}\b(?P<context>{token_context})\b",
            re.IGNORECASE,
        )

        total_values: list[int] = []
        component_values: list[int] = []
        for line in text.splitlines():
            matches = [
                (match.group("context").lower(), int(match.group("tokens").replace(",", "")))
                for pattern in (context_before_tokens, context_before_number, tokens_before_context)
                for match in pattern.finditer(line)
            ]
            for context, tokens in matches:
                if context in total_context:
                    total_values.append(tokens)
                elif context in component_context:
                    component_values.append(tokens)
        if total_values:
            return [max(total_values)]
        return component_values

    @staticmethod
    def _extract_json_token_usage(text: str) -> list[int]:
        totals: list[int] = []
        for line in text.splitlines():
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            total = ConsoleApp._json_token_total(value)
            if total is not None:
                totals.append(total)
        return totals

    @staticmethod
    def _json_token_total(value: object) -> int | None:
        if isinstance(value, dict):
            direct_keys = ("total_tokens", "totalTokens", "tokens_total", "tokensTotal")
            for key in direct_keys:
                direct_value = value.get(key)
                if isinstance(direct_value, int):
                    return direct_value
            token_keys = (
                "input_tokens",
                "inputTokens",
                "prompt_tokens",
                "promptTokens",
                "output_tokens",
                "outputTokens",
                "completion_tokens",
                "completionTokens",
            )
            subtotal = sum(item for key in token_keys if isinstance((item := value.get(key)), int))
            if subtotal:
                return subtotal
            for nested in value.values():
                total = ConsoleApp._json_token_total(nested)
                if total is not None:
                    return total
        if isinstance(value, list):
            subtotals = [total for item in value if (total := ConsoleApp._json_token_total(item)) is not None]
            if subtotals:
                return sum(subtotals)
        return None

    def _render_command_result(self, command: str, stdout: str, stderr: str, returncode: int) -> Text:
        text = Text()
        text.append(f"{self._t('command_result_returncode')}: {returncode}\n", style="bold")
        text.append(f"{self._t('command_result_stdout')}:\n{stdout.strip() or self._t('empty')}\n\n", style="white")
        if stderr.strip():
            text.append(f"{self._t('command_result_stderr')}:\n{stderr.strip()}\n", style="red")
        text.append(f"{self._t('command_result_command')}: {command}", style="dim")
        return text

    def _render_rollback_result(self, result) -> Text:
        text = Text()
        text.append(f"{self._t('rollback_changed_count')}: {result.changed_count}\n", style="bold")
        text.append(f"{self._t('rollback_restored')}: {', '.join(result.restored) or self._t('empty')}\n", style="white")
        text.append(f"{self._t('rollback_reverted')}: {', '.join(result.reverted) or self._t('empty')}\n", style="white")
        text.append(f"{self._t('rollback_removed')}: {', '.join(result.removed) or self._t('empty')}\n", style="white")
        text.append(f"snapshot: {result.snapshot_id}", style="dim")
        return text

    @staticmethod
    def _task_summary(text: str) -> str:
        return shorten(" ".join(text.split()), width=80, placeholder="...")

    def _result_summary(self, result) -> str:
        return f"{result.agent_name} rc={result.returncode} {self._task_summary(result.text or result.stderr or self._t('empty'))}"

    @staticmethod
    def _history_summary(record: dict[str, object]) -> str:
        pieces = [
            str(record.get(key, ""))
            for key in ("task", "agent", "role", "stdout", "stderr", "message")
            if record.get(key)
        ]
        return shorten(" ".join(pieces), width=96, placeholder="...")

    @staticmethod
    def _short_path(path: str) -> str:
        return shorten(path.replace("\n", " "), width=64, placeholder="...")

    @staticmethod
    def _short_text(text: str, width: int) -> str:
        return shorten(" ".join(text.split()), width=width, placeholder="...")

    def _t(self, key: str) -> str:
        return translate(self.language, key)
