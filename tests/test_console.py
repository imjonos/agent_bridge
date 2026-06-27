from __future__ import annotations

import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from agent_bridge.agents.base import AgentResult
from agent_bridge.config import Settings
from agent_bridge.services.history import HistoryService
from agent_bridge.services.workflow import Workflow
from agent_bridge.ui.console import CODEX_STATUS_TIMEOUT_SEC, ConsoleApp
from agent_bridge.ui.translations import DEFAULT_LANGUAGE, TRANSLATIONS


class FakeWorkflow:
    def __init__(self, history: HistoryService) -> None:
        from types import SimpleNamespace

        self.state = SimpleNamespace(
            current_task=None,
            last_builder_result=None,
            last_reviewer_result=None,
            last_completed_role=None,
            status="waiting",
        )
        self.history = history

    def set_task(self, text: str) -> None:
        self.state.current_task = text.strip()


class StubAgent:
    name = "stub"
    role = "builder"

    def run(self, prompt: str, stream_callback=None) -> AgentResult:
        return AgentResult("stub", "builder", prompt, "", "", 0, 0.0)


class ConsoleTests(TestCase):
    def _make_app(self, project_dir: Path) -> ConsoleApp:
        settings = Settings(project_dir=str(project_dir))
        history = HistoryService(project_dir / ".agent-bridge" / "test-history")
        workflow = FakeWorkflow(history)
        return ConsoleApp(settings=settings, workflow=workflow, history=history)

    def test_save_task_text_updates_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            app = self._make_app(project_dir)

            app.save_task_text(" first line\nsecond line ")

            self.assertEqual(app.workflow.state.current_task, "first line\nsecond line")

    def test_default_language_is_english(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            self.assertEqual(app.language, DEFAULT_LANGUAGE)
            self.assertEqual(app._t("task_title"), "Current task")

    def test_toggle_language_switches_to_russian(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            app.action_toggle_language()

            self.assertEqual(app.language, "ru")
            self.assertEqual(app._t("task_title"), "Текущая задача")

    def test_translation_sets_have_same_keys(self) -> None:
        english_keys = set(TRANSLATIONS["en"])
        russian_keys = set(TRANSLATIONS["ru"])

        self.assertEqual(russian_keys, english_keys)

    def test_run_binding_uses_f5_go(self) -> None:
        bindings = {binding.action: binding for binding in ConsoleApp.BINDINGS}

        self.assertEqual(bindings["save_task"].key, "f2")
        self.assertEqual(bindings["save_task"].description, "Save")
        self.assertEqual(bindings["run_next"].key, "f5")
        self.assertEqual(bindings["run_next"].description, "Go")
        self.assertEqual(bindings["stop_running"].key, "f6")
        self.assertEqual(bindings["stop_running"].description, "Stop")
        self.assertEqual(bindings["rollback_changes"].key, "ctrl+z")
        self.assertEqual(bindings["rollback_changes"].description, "Rollback")
        self.assertNotIn("show_history", bindings)

    def test_menu_shows_f5_go_and_hides_timeline_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            first_row = app._render_menu_text(app._menu_commands_first_row()).plain
            second_row = app._render_menu_text(app._menu_commands_second_row()).plain

            self.assertIn("F5 Go", first_row)
            self.assertIn("F6 Stop", first_row)
            self.assertIn("^Z Rollback", second_row)
            self.assertIn("F2 Save", first_row)
            self.assertNotIn("^S", first_row)
            self.assertNotIn("^U", first_row)
            self.assertNotIn("^H", second_row)
            self.assertNotIn("Timeline", second_row)

    def test_autosave_before_run_saves_changed_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app._task_editor = lambda: SimpleNamespace(text="new task")  # type: ignore[method-assign]

            self.assertTrue(app._autosave_task_before_run())
            self.assertEqual(app.workflow.state.current_task, "new task")

    def test_autosave_before_run_skips_unchanged_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app.workflow.state.current_task = "saved task"
            app._task_editor = lambda: SimpleNamespace(text=" saved task ")  # type: ignore[method-assign]
            calls = 0

            def fail_if_saved(_: str) -> None:
                nonlocal calls
                calls += 1

            app.save_task_text = fail_if_saved  # type: ignore[method-assign]

            self.assertTrue(app._autosave_task_before_run())
            self.assertEqual(calls, 0)

    def test_ctrl_s_is_not_registered_as_save_shortcut(self) -> None:
        keys = {binding.key for binding in ConsoleApp.BINDINGS}

        self.assertNotIn("ctrl+s", keys)

    def test_console_translation_keys_exist(self) -> None:
        console_path = Path(__file__).resolve().parents[1] / "agent_bridge" / "ui" / "console.py"
        console_source = console_path.read_text(encoding="utf-8")
        used_keys = set(re.findall(r"_t\([\"']([^\"']+)[\"']\)", console_source))

        self.assertTrue(used_keys)
        self.assertLessEqual(used_keys, set(TRANSLATIONS["en"]))

    def test_extract_token_usage_reads_json_usage(self) -> None:
        text = '{"usage":{"input_tokens":1200,"output_tokens":345}}'

        self.assertEqual(ConsoleApp._extract_token_usage(text), 1545)

    def test_extract_token_usage_uses_max_for_multiple_json_totals(self) -> None:
        text = '{"total_tokens": 100}\n{"total_tokens": 250}'

        self.assertEqual(ConsoleApp._extract_token_usage(text), 250)

    def test_extract_token_usage_reads_multiline_json_without_double_counting(self) -> None:
        text = """{
  "usage": {
    "input_tokens": 1200,
    "output_tokens": 345
  }
}
input tokens: 10
output tokens: 20
"""

        self.assertEqual(ConsoleApp._extract_token_usage(text), 1545)

    def test_extract_token_usage_reads_textual_total(self) -> None:
        text = "Token usage: total tokens: 2,048"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 2048)

    def test_extract_token_usage_prefers_textual_total_over_breakdown(self) -> None:
        text = "Token usage: total tokens: 300 input tokens: 120 output tokens: 180"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 300)

    def test_extract_token_usage_prefers_explicit_total(self) -> None:
        text = "input: 50 tokens output: 50 tokens total: 100 tokens"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 100)

    def test_extract_token_usage_does_not_use_json_keywords_for_text_total(self) -> None:
        text = '{"used": 100}\ninput tokens: 50\noutput tokens: 25'

        self.assertEqual(ConsoleApp._extract_token_usage(text), 75)

    def test_extract_token_usage_prefers_json_total_over_textual_components(self) -> None:
        text = '{"total_tokens": 5000}\ninput tokens: 50\noutput tokens: 25'

        self.assertEqual(ConsoleApp._extract_token_usage(text), 5000)

    def test_extract_token_usage_ignores_used_in_prose(self) -> None:
        text = "The agent used the tool. input tokens: 50 output tokens: 50"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 100)

    def test_extract_token_usage_sums_textual_breakdown_without_total(self) -> None:
        text = "Token usage: input tokens: 120 output tokens: 180"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 300)

    def test_extract_token_usage_sums_equal_textual_components(self) -> None:
        text = "Token usage: input tokens: 100 output tokens: 100"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 200)

    def test_extract_token_usage_reads_total_before_token_word(self) -> None:
        text = "Total: 2,048 tokens"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 2048)

    def test_extract_token_usage_prefers_total_across_lines(self) -> None:
        text = "input tokens: 120\noutput tokens: 180\ntotal tokens: 300"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 300)

    def test_extract_token_usage_dedupes_repeated_total(self) -> None:
        text = "total tokens: 300\ntotal tokens: 300"

        self.assertEqual(ConsoleApp._extract_token_usage(text), 300)

    def test_update_usage_dedupes_total_repeated_in_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            result = SimpleNamespace(
                stdout="total tokens: 300",
                stderr="total tokens: 300",
                duration_sec=1.0,
            )

            app._update_usage("builder", result)

            self.assertEqual(app._usage["builder"]["tokens"], 300)

    def test_update_usage_prefers_codex_status_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            result = SimpleNamespace(
                agent_name="codex",
                stdout="total tokens: 100",
                stderr="",
                duration_sec=1.0,
            )
            status_result = SimpleNamespace(
                stdout="total tokens: 250",
                stderr="",
                returncode=0,
            )

            with patch("agent_bridge.ui.console.run_process", return_value=status_result) as run_process_mock:
                app._update_usage("builder", result, codex_status_tokens=250)

            self.assertEqual(app._usage["builder"]["tokens"], 250)
            run_process_mock.assert_not_called()

    def test_update_usage_falls_back_when_codex_status_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            result = SimpleNamespace(
                agent_name="codex",
                stdout="total tokens: 100",
                stderr="",
                duration_sec=1.0,
            )

            app._update_usage("builder", result, codex_status_tokens=None)

            self.assertEqual(app._usage["builder"]["tokens"], 100)
            self.assertTrue(app._usage["builder"]["tokens_known"])

    def test_read_codex_status_tokens_uses_status_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            status_result = SimpleNamespace(
                stdout="total tokens: 250",
                stderr="",
                returncode=0,
            )

            with patch("agent_bridge.ui.console.run_process", return_value=status_result) as run_process_mock:
                tokens = app._read_codex_status_tokens()

            self.assertEqual(tokens, 250)
            self.assertEqual(run_process_mock.call_args.kwargs["timeout"], CODEX_STATUS_TIMEOUT_SEC)

    def test_read_codex_status_tokens_uses_top_level_status_without_exec_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app.settings.codex_base_args = "exec --sandbox workspace-write"
            status_result = SimpleNamespace(
                stdout="total tokens: 250",
                stderr="",
                returncode=0,
            )

            with patch("agent_bridge.ui.console.run_process", return_value=status_result) as run_process_mock:
                app._read_codex_status_tokens()

            self.assertEqual(
                run_process_mock.call_args.args[0],
                ["codex", "status"],
            )

    def test_restore_usage_from_history_does_not_reuse_saved_codex_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        '{"type":"task_created","task":"task"}',
                        '{"type":"builder_result","agent":"codex","stdout":"","stderr":"","duration_sec":1.0,"tokens":250}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            app = self._make_app(project_dir)

            self.assertEqual(app._usage["builder"]["tokens"], 0)
            self.assertFalse(app._usage["builder"]["tokens_known"])

    def test_handle_codex_token_refresh_persists_tokens_to_latest_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app.workflow.history.append("task_created", {"task": "task"})
            app.workflow.history.append("builder_result", {"agent": "codex", "stdout": ""})
            history_refreshes = 0
            app._refresh_status_card = lambda: None  # type: ignore[method-assign]

            def refresh_history_log() -> None:
                nonlocal history_refreshes
                history_refreshes += 1

            app._refresh_history_log = refresh_history_log  # type: ignore[method-assign]

            app._handle_codex_token_refresh("builder", {"builder_result"}, 250)

            records = app.workflow.history.read_current_session()
            self.assertEqual(records[-1]["tokens"], 250)
            self.assertEqual(app._usage["builder"]["tokens"], 250)
            self.assertEqual(history_refreshes, 1)

    def test_reviewer_codex_status_tokens_are_not_read_from_global_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            result = SimpleNamespace(agent_name="codex", role="reviewer")

            with patch.object(app, "_read_codex_status_tokens", return_value=250) as status_mock:
                tokens = app._read_codex_status_tokens_for_result(result)

            self.assertIsNone(tokens)
            status_mock.assert_not_called()

    def test_extract_token_usage_does_not_guess_from_output_length(self) -> None:
        text = "Normal agent output without usage metadata."

        self.assertIsNone(ConsoleApp._extract_token_usage(text))

    def test_render_stream_line_outputs_clean_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            rendered = app._render_stream_line("Builder", "stdout", "hello")

            self.assertEqual(rendered.plain, "hello")
            self.assertNotIn("Builder", rendered.plain)
            self.assertNotIn("out", rendered.plain)

    def test_render_stream_line_does_not_label_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            rendered = app._render_stream_line("Builder", "stderr", "\x1b[32mboom\x1b[0m")

            self.assertEqual(rendered.plain, "boom")
            self.assertNotIn("log", rendered.plain)
            self.assertNotIn("red", {str(span.style) for span in rendered.spans})

    def test_render_stream_line_highlights_shell_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            rendered = app._render_stream_line("Builder", "stdout", "$ git diff --stat")

            self.assertIsInstance(rendered, Syntax)

    def test_render_stream_line_highlights_diff_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            rendered = app._render_stream_line("Builder", "stdout", "diff --git a/app.py b/app.py")

            self.assertIsInstance(rendered, Syntax)

    def test_stream_line_style_marks_only_error_words_red(self) -> None:
        self.assertEqual(ConsoleApp._stream_line_style("stderr", "normal progress"), "white")
        self.assertEqual(ConsoleApp._stream_line_style("stderr", "fatal failure"), "red")

    def test_format_usage_summary_formats_known_and_unknown_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            known = {"runs": 2, "duration": 3.5, "tokens": 420, "tokens_known": True}
            unknown = {"runs": 1, "duration": 0.25, "tokens": 0, "tokens_known": False}

            self.assertEqual(app._format_usage_summary(known), "2 runs / 3.5s / tokens 420")
            self.assertEqual(app._format_usage_summary(unknown), "1 runs / 0.2s / tokens n/a")

    def test_running_status_badge_has_blue_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            badge = app._status_badge("running")

            self.assertEqual(str(badge.style), "white on blue")

    def test_render_agent_chip_contains_usage_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            usage = {"runs": 2, "duration": 3.5, "tokens": 420, "tokens_known": True}

            rendered = app._render_agent_chip("Builder", "codex", "success", usage)

            self.assertIn("Builder", rendered.plain)
            self.assertIn("2 runs / 3.5s / tokens 420", rendered.plain)

    def test_active_run_summary_contains_role_engine_start_and_elapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            app._set_running_state("builder")
            summary = app._active_run_summary()

            self.assertIn("Builder (codex)", summary)
            self.assertRegex(summary, r"from \d{2}:\d{2}:\d{2} / \d{2}:\d{2}")

    def test_active_run_summary_is_empty_when_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app._set_running_state("reviewer")
            app.workflow.state.status = "success"

            self.assertEqual(app._active_run_summary(), "not set")

    def test_active_run_summary_uses_explicit_tool_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))

            app._set_running_state("tools", active_title="Git diff")

            self.assertIn("Git diff", app._active_run_summary())

    def test_format_elapsed_uses_minutes_or_hours(self) -> None:
        self.assertEqual(ConsoleApp._format_elapsed(65), "01:05")
        self.assertEqual(ConsoleApp._format_elapsed(3661), "1:01:01")

    def test_append_final_result_writes_only_agent_result_panel(self) -> None:
        class FakeLog:
            def __init__(self) -> None:
                self.entries: list[object] = []

            def write(self, value: object) -> None:
                self.entries.append(value)

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            log = FakeLog()
            app._live_log = lambda: log  # type: ignore[method-assign]
            result = SimpleNamespace(
                agent_name="codex",
                text="# Done",
                stderr="\x1b[31mwarning\x1b[0m",
                returncode=1,
                duration_sec=1.25,
            )

            app._append_final_result("Builder", result, "error")

            panels = [entry for entry in log.entries if isinstance(entry, Panel)]
            self.assertEqual(len(panels), 1)
            self.assertIsInstance(panels[0].renderable, Markdown)
            self.assertIn("Builder", str(panels[0].title))

    def test_refresh_ui_renders_last_result_in_live_log(self) -> None:
        class FakeLog:
            def __init__(self) -> None:
                self.entries: list[object] = []
                self.clear_calls = 0

            def clear(self) -> None:
                self.clear_calls += 1
                self.entries.clear()

            def write(self, value: object) -> None:
                self.entries.append(value)

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            log = FakeLog()
            app._ui_ready = True
            app._live_log = lambda: log  # type: ignore[method-assign]
            app.workflow.state.last_reviewer_result = SimpleNamespace(
                agent_name="opencode",
                role="reviewer",
                text="Recovered reviewer output",
                returncode=0,
                duration_sec=1.25,
            )

            app._update_initial_result_widgets()

            panels = [entry for entry in log.entries if isinstance(entry, Panel)]
            self.assertEqual(log.clear_calls, 1)
            self.assertEqual(len(panels), 1)
            self.assertIn("Reviewer", str(panels[0].title))
            self.assertEqual(panels[0].renderable.markup, "Recovered reviewer output")

    def test_initial_result_widgets_follow_last_completed_role(self) -> None:
        class FakeLog:
            def __init__(self) -> None:
                self.entries: list[object] = []
                self.clear_calls = 0

            def clear(self) -> None:
                self.clear_calls += 1
                self.entries.clear()

            def write(self, value: object) -> None:
                self.entries.append(value)

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            log = FakeLog()
            app._ui_ready = True
            app._live_log = lambda: log  # type: ignore[method-assign]
            app.workflow.state.last_completed_role = "builder"
            app.workflow.state.last_builder_result = SimpleNamespace(
                agent_name="codex",
                role="builder",
                text="Latest builder fix",
                returncode=0,
                duration_sec=1.25,
            )
            app.workflow.state.last_reviewer_result = SimpleNamespace(
                agent_name="opencode",
                role="reviewer",
                text="Stale reviewer output",
                returncode=0,
                duration_sec=1.0,
            )

            app._update_initial_result_widgets()

            panels = [entry for entry in log.entries if isinstance(entry, Panel)]
            self.assertEqual(log.clear_calls, 1)
            self.assertEqual(len(panels), 1)
            self.assertIn("Builder", str(panels[0].title))
            self.assertEqual(panels[0].renderable.markup, "Latest builder fix")

    def test_restart_restores_task_and_last_result_into_console_widgets(self) -> None:
        class FakeLog:
            def __init__(self) -> None:
                self.entries: list[object] = []
                self.clear_calls = 0

            def clear(self) -> None:
                self.clear_calls += 1
                self.entries.clear()

            def write(self, value: object) -> None:
                self.entries.append(value)

        class FakeEditor:
            def __init__(self) -> None:
                self.text = ""

            def load_text(self, text: str) -> None:
                self.text = text

        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            history_dir = project_dir / ".agent-bridge" / "test-history"
            history_dir.mkdir(parents=True)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        '{"type":"task_created","task":"Persisted task"}',
                        '{"type":"builder_result","agent":"codex","role":"builder","stdout":"Builder output","stderr":"","returncode":0,"duration_sec":1.0}',
                        '{"type":"reviewer_result","agent":"opencode","role":"reviewer","stdout":"Recovered reviewer output","stderr":"","returncode":0,"duration_sec":1.0}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            settings = Settings(project_dir=str(project_dir))
            history = HistoryService(history_dir)
            workflow = Workflow(settings, StubAgent(), StubAgent(), history)
            app = ConsoleApp(settings=settings, workflow=workflow, history=history)
            log = FakeLog()
            editor = FakeEditor()
            app._ui_ready = True
            app._live_log = lambda: log  # type: ignore[method-assign]
            app._task_editor = lambda: editor  # type: ignore[method-assign]
            app._refresh_status_card = lambda: None  # type: ignore[method-assign]
            app._refresh_config_card = lambda: None  # type: ignore[method-assign]
            app._refresh_history_log = lambda: None  # type: ignore[method-assign]

            app._refresh_ui()

            panels = [entry for entry in log.entries if isinstance(entry, Panel)]
            self.assertEqual(workflow.state.current_task, "Persisted task")
            self.assertEqual(editor.text, "Persisted task")
            self.assertEqual(log.clear_calls, 1)
            self.assertEqual(len(panels), 1)
            self.assertIn("Reviewer", str(panels[0].title))
            self.assertEqual(panels[0].renderable.markup, "Recovered reviewer output")

    def test_restore_agent_statuses_uses_restored_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            app.workflow.state.last_builder_result = SimpleNamespace(returncode=0)
            app.workflow.state.last_reviewer_result = SimpleNamespace(returncode=1)

            app._restore_agent_statuses()

            self.assertEqual(app._builder_status, "success")
            self.assertEqual(app._reviewer_status, "error")

    def test_new_task_persists_clear_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = self._make_app(Path(tmp_dir))
            cleared = False

            app._task_editor = lambda: SimpleNamespace(clear=lambda: None, focus=lambda: None)  # type: ignore[method-assign]
            app._refresh_ui = lambda: None  # type: ignore[method-assign]
            app._append_activity = lambda *args, **kwargs: None  # type: ignore[method-assign]

            def append(event_type: str, payload=None) -> None:
                nonlocal cleared
                cleared = event_type == "task_cleared"

            app.workflow.history.append = append  # type: ignore[method-assign]

            app.action_new_task()

            self.assertTrue(cleared)
