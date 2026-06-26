from __future__ import annotations

import re
from textwrap import shorten
from typing import Callable

from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Markdown, RichLog, Static, TextArea

from ..config import Settings
from ..services.git_context import get_git_diff
from ..services.history import HistoryService
from ..services.runner import run_shell_command
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
        height: 5;
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
        height: 4;
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
        height: 8;
    }

    #usage_panel {
        height: 6;
    }

    #history_panel {
        height: 1fr;
    }

    #live_panel {
        height: 2fr;
    }

    #result_panel {
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

    #result_output {
        height: 1fr;
        margin-top: 0;
    }

    #live_log,
    #history_log {
        height: 1fr;
        margin-top: 0;
    }

    """

    BINDINGS = [
        Binding("ctrl+s", "save_task", "Save task", show=True),
        Binding("ctrl+n", "new_task", "New task", show=False),
        Binding("ctrl+b", "run_builder", "Builder", show=False),
        Binding("ctrl+r", "send_to_reviewer", "Reviewer", show=False),
        Binding("ctrl+f", "fix_builder", "Fix", show=False),
        Binding("ctrl+d", "show_diff", "Diff", show=False),
        Binding("ctrl+t", "run_tests", "Tests", show=False),
        Binding("ctrl+h", "show_history", "Timeline", show=False),
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
        self._usage = {
            "builder": {"runs": 0, "duration": 0.0, "stdout": 0, "stderr": 0, "tokens": 0},
            "reviewer": {"runs": 0, "duration": 0.0, "stdout": 0, "stderr": 0, "tokens": 0},
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
                with Container(id="usage_panel", classes="panel"):
                    yield Static(Text(self._t("usage_title"), style="bold white"), id="usage_title")
                    yield Static(id="usage_card")
                with Container(id="history_panel", classes="panel"):
                    yield Static(Text(self._t("history_title"), style="bold white"), id="history_title")
                    yield RichLog(id="history_log", markup=True, wrap=True, auto_scroll=True)
            with Vertical(id="workspace"):
                with Container(id="live_panel", classes="panel"):
                    yield Static(Text(self._t("live_output_title"), style="bold white"), id="live_title")
                    yield Static(id="live_meta")
                    yield RichLog(id="live_log", markup=True, wrap=True, auto_scroll=True)
                with Container(id="result_panel", classes="panel"):
                    yield Static(Text(self._t("final_result_title"), style="bold white"), id="result_title")
                    yield Static(id="result_meta")
                    yield Markdown(self._t("final_result_empty"), id="result_output")
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
        self.workflow.state.status = "waiting"
        self._builder_status = "waiting"
        self._reviewer_status = "waiting"
        self._active_role = "-"
        self._task_editor().clear()
        self._set_message(self._t("new_task_title"))
        self._append_activity(self._t("new_task_title"), self._t("new_task_activity"), style="cyan")
        self._refresh_ui()
        self._task_editor().focus()

    def action_clear_task(self) -> None:
        self._task_editor().clear()
        self._set_message(self._t("task_cleared"))
        self._task_editor().focus()

    def action_run_builder(self) -> None:
        self._start_worker("builder", self._builder_worker, self._set_message)

    def action_send_to_reviewer(self) -> None:
        self._start_worker("reviewer", self._reviewer_worker, self._set_message)

    def action_fix_builder(self) -> None:
        self._start_worker("builder_fix", self._fix_worker, self._set_message)

    def action_show_diff(self) -> None:
        self._start_worker("tools", self._git_diff_worker, self._set_message)

    def action_run_tests(self) -> None:
        self._start_worker("tools", self._tests_worker, self._set_message)

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

    def _start_worker(self, group: str, worker: Callable[[], None], status_message: Callable[[str], None]) -> None:
        status_message(self._t("run_started"))
        self._set_running_state(group)
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

    def _handle_builder_result(self, result, is_fix: bool = False) -> None:
        title = "Builder fix" if is_fix else "Builder"
        self._builder_status = "success" if result.returncode == 0 else "error"
        self._set_message(self._t("builder_done"))
        self._update_result_widgets(title, result, self._builder_status)
        self._update_usage("builder", result)
        self._refresh_history_log()
        self._append_activity(title, self._result_summary(result), style="green" if result.returncode == 0 else "red")
        self._refresh_status_card()

    def _handle_reviewer_result(self, result) -> None:
        self._reviewer_status = "success" if result.returncode == 0 else "error"
        self._set_message(self._t("reviewer_done"))
        self._update_result_widgets("Reviewer", result, self._reviewer_status)
        self._update_usage("reviewer", result)
        self._refresh_history_log()
        self._append_activity("Reviewer", self._result_summary(result), style="green" if result.returncode == 0 else "red")
        self._refresh_status_card()

    def _handle_diff_result(self, diff: str) -> None:
        self.workflow.state.status = "success"
        self._set_message(self._t("diff_ready"))
        self._activity_log().write(Text("Git diff", style="bold magenta"))
        self._activity_log().write(Syntax(diff or self._t("empty"), "diff", word_wrap=False))
        self._refresh_history_log()
        self._refresh_status_card()

    def _handle_tests_result(self, result) -> None:
        self.workflow.state.status = "success" if result.returncode == 0 else "error"
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

    def _handle_worker_error(self, title: str, exc: Exception) -> None:
        message = str(exc)
        self.workflow.state.status = "error"
        if title.startswith("Builder"):
            self._builder_status = "error"
            if self._ui_ready:
                self._result_meta().update(self._render_agent_meta("Builder", self.settings.builder_agent, None, self._builder_status))
        elif title == "Reviewer":
            self._reviewer_status = "error"
            if self._ui_ready:
                self._result_meta().update(self._render_agent_meta("Reviewer", self.settings.reviewer_agent, None, self._reviewer_status))
        self._append_activity(title, message, style="red")
        self._set_error(f"{title}: {message}")
        self._refresh_status_card()

    def _refresh_ui(self) -> None:
        if not self._ui_ready:
            return
        self._refresh_status_card()
        self._refresh_config_card()
        self._refresh_usage_card()
        self._update_initial_result_widgets()
        self._refresh_history_log()
        self._set_task_editor(self.workflow.state.current_task or "")

    def _refresh_status_card(self) -> None:
        if not self._ui_ready:
            return
        self._status_card().update(self._render_status_card())
        self._builder_chip().update(
            self._render_agent_chip("Builder", self.settings.builder_agent, self._builder_status)
        )
        self._reviewer_chip().update(
            self._render_agent_chip("Reviewer", self.settings.reviewer_agent, self._reviewer_status)
        )

    def _refresh_config_card(self) -> None:
        if not self._ui_ready:
            return
        self._config_card().update(self._render_config_card())

    def _refresh_usage_card(self) -> None:
        if not self._ui_ready:
            return
        self._usage_card().update(self._render_usage_card())

    def _refresh_history_log(self) -> None:
        if not self._ui_ready:
            return
        log = self._history_log()
        log.clear()
        for record in self.history.read_current_session():
            log.write(self._render_history_entry(record))

    def _update_initial_result_widgets(self) -> None:
        if not self._ui_ready:
            return
        result = self.workflow.state.last_reviewer_result or self.workflow.state.last_builder_result
        if result is None:
            self._result_meta().update(self._render_agent_meta("Result", "-", None, "waiting"))
            self._result_output().update(self._t("final_result_empty"))
            self._live_meta().update(self._render_live_meta())
            return
        title = "Reviewer" if result.role == "reviewer" else "Builder"
        status = "success" if result.returncode == 0 else "error"
        self._update_result_widgets(title, result, status)

    def _update_result_widgets(self, title: str, result, status: str) -> None:
        if not self._ui_ready:
            return
        self._result_meta().update(self._render_agent_meta(title, result.agent_name, result, status))
        output = result.text or result.stderr.strip() or self._t("empty_output")
        self._result_output().update(output)
        self._live_meta().update(self._render_live_meta())

    def _render_status_card(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, no_wrap=True)
        table.add_column(ratio=2)
        table.add_row(Text(self._t("status"), style="grey70"), self._status_badge(self.workflow.state.status))
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

    def _render_usage_card(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, no_wrap=True)
        table.add_column(ratio=2)
        for role in ("builder", "reviewer"):
            usage = self._usage[role]
            table.add_row(
                Text(role, style="grey70"),
                Text(
                    self._t("usage_runs").format(
                        runs=usage["runs"],
                        duration=usage["duration"],
                        tokens=usage["tokens"],
                    ),
                    style="white",
                ),
            )
            table.add_row(
                Text("", style="grey70"),
                Text(self._t("usage_chars").format(stdout=usage["stdout"], stderr=usage["stderr"]), style="grey70"),
            )
        return table

    def _render_live_meta(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, no_wrap=True)
        table.add_column(ratio=3)
        table.add_row(Text(self._t("live_output_title"), style="bold white"), Text(self._active_role, style="yellow"))
        table.add_row(Text(self._t("live_meta_state"), style="grey70"), Text(self._last_message, style="white"))
        return table

    def _render_agent_chip(self, title: str, engine: str, status: str) -> Text:
        text = Text()
        text.append(f"{title}\n", style="bold white")
        text.append(self._status_label(status), style=self._status_text_style(status))
        return text

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

    def _prepare_live_output(self, title: str) -> None:
        if not self._ui_ready:
            return
        self._active_role = title
        log = self._live_log()
        log.clear()
        log.write(Text(f"{title}: {self._t('prompt_and_process')}", style="yellow"))
        self._live_meta().update(self._render_live_meta())
        self._append_activity(title, self._t("process_started"), style="yellow")

    def _append_live_output(self, title: str, stream_name: str, line: str) -> None:
        if not self._ui_ready or not line:
            return
        style = self._stream_line_style(stream_name, line)
        prefix_style = "red" if stream_name == "stderr" else "cyan"
        text = Text()
        text.append(f"{title:<8} ", style="grey70")
        text.append(f"{stream_name:<6} ", style=prefix_style)
        text.append(line, style=style)
        self._live_log().write(text)
        if style == "red":
            self._append_activity(title, self._short_text(line, 140), style="red")

    def _update_usage(self, role: str, result) -> None:
        usage = self._usage[role]
        usage["runs"] += 1
        usage["duration"] += result.duration_sec
        usage["stdout"] += len(result.stdout)
        usage["stderr"] += len(result.stderr)
        usage["tokens"] += self._extract_token_usage(result.stdout + "\n" + result.stderr)
        self._refresh_usage_card()

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
            ("^S", self._t("save")),
            ("^N", self._t("new")),
            ("^B", self._t("command_build")),
            ("^R", self._t("command_review")),
            ("^F", self._t("command_fix")),
        ]

    def _menu_commands_second_row(self) -> list[tuple[str, str]]:
        return [
            ("^D", self._t("command_diff")),
            ("^T", self._t("command_tests")),
            ("^H", self._t("history_title")),
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
            "approved": "green",
            "error": "red",
        }.get(event_type, "white")
        label = {
            "task_created": "task",
            "builder_result": "build",
            "reviewer_result": "review",
            "fix_result": "fix",
            "test_result": "test",
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

    def _set_running_state(self, action: str) -> None:
        if action.startswith("builder"):
            self._builder_status = "running"
            self.workflow.state.status = "running"
            self._active_role = "Builder"
            if self._ui_ready:
                self._result_meta().update(self._render_agent_meta("Builder", self.settings.builder_agent, None, self._builder_status))
                self._live_meta().update(self._render_live_meta())
        elif action == "reviewer":
            self._reviewer_status = "running"
            self.workflow.state.status = "running"
            self._active_role = "Reviewer"
            if self._ui_ready:
                self._result_meta().update(self._render_agent_meta("Reviewer", self.settings.reviewer_agent, None, self._reviewer_status))
                self._live_meta().update(self._render_live_meta())
        elif action == "tools":
            self.workflow.state.status = "running"
        self._set_message(self._t("run_started"))
        self._refresh_status_card()

    def _refresh_translated_text(self) -> None:
        if not self._ui_ready:
            return
        self.query_one("#task_title", Static).update(Text(self._t("task_title"), style="bold white"))
        self.query_one("#usage_title", Static).update(Text(self._t("usage_title"), style="bold white"))
        self.query_one("#history_title", Static).update(Text(self._t("history_title"), style="bold white"))
        self.query_one("#live_title", Static).update(Text(self._t("live_output_title"), style="bold white"))
        self.query_one("#result_title", Static).update(Text(self._t("final_result_title"), style="bold white"))
        self.query_one("#menu_hint", Static).update(Text(self._t("commands_title"), style="bold white"))
        self.query_one("#menu_commands_1", Static).update(self._render_menu_text(self._menu_commands_first_row()))
        self.query_one("#menu_commands_2", Static).update(self._render_menu_text(self._menu_commands_second_row()))
        self._task_editor().placeholder = self._t("task_placeholder")
        self._live_meta().update(self._render_live_meta())

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

    def _usage_card(self) -> Static:
        return self.query_one("#usage_card", Static)

    def _live_meta(self) -> Static:
        return self.query_one("#live_meta", Static)

    def _result_meta(self) -> Static:
        return self.query_one("#result_meta", Static)

    def _result_output(self) -> Markdown:
        return self.query_one("#result_output", Markdown)

    def _live_log(self) -> RichLog:
        return self.query_one("#live_log", RichLog)

    def _activity_log(self) -> RichLog:
        return self._live_log()

    def _history_log(self) -> RichLog:
        return self.query_one("#history_log", RichLog)

    def _set_task_editor(self, text: str) -> None:
        self._task_editor().load_text(text)

    def _status_badge(self, status: str) -> Text:
        styles = {
            "waiting": "black on bright_white",
            "running": "black on yellow",
            "success": "black on green",
            "error": "white on red",
        }
        return Text(f" {self._status_label(status)} ", style=styles.get(status, "white on black"))

    def _status_label(self, status: str) -> str:
        return self._t(f"status_{status}") if status in {"waiting", "running", "success", "error"} else status.upper()

    @staticmethod
    def _status_text_style(status: str) -> str:
        return {
            "waiting": "grey70",
            "running": "yellow",
            "success": "green",
            "error": "red",
        }.get(status, "white")

    @staticmethod
    def _stream_line_style(stream_name: str, line: str) -> str:
        if stream_name == "stderr":
            return "red"
        if re.search(r"\b(error|failed|exception|traceback|fatal)\b", line, re.IGNORECASE):
            return "red"
        if re.search(r"\b(warn|warning|retry)\b", line, re.IGNORECASE):
            return "yellow"
        return "white"

    @staticmethod
    def _extract_token_usage(text: str) -> int:
        explicit_total = 0
        for match in re.finditer(r"([\d,]+)\s+(?:tokens?|tok)\b", text, re.IGNORECASE):
            explicit_total += int(match.group(1).replace(",", ""))
        if explicit_total:
            return explicit_total
        return max(1, len(text) // 4) if text.strip() else 0

    def _render_command_result(self, command: str, stdout: str, stderr: str, returncode: int) -> Text:
        text = Text()
        text.append(f"{self._t('command_result_returncode')}: {returncode}\n", style="bold")
        text.append(f"{self._t('command_result_stdout')}:\n{stdout.strip() or self._t('empty')}\n\n", style="white")
        if stderr.strip():
            text.append(f"{self._t('command_result_stderr')}:\n{stderr.strip()}\n", style="red")
        text.append(f"{self._t('command_result_command')}: {command}", style="dim")
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
