from __future__ import annotations

import re
from pathlib import Path
import tempfile
from unittest import TestCase

from agent_bridge.config import Settings
from agent_bridge.services.history import HistoryService
from agent_bridge.ui.console import ConsoleApp
from agent_bridge.ui.translations import DEFAULT_LANGUAGE, TRANSLATIONS


class FakeWorkflow:
    def __init__(self, history: HistoryService) -> None:
        from types import SimpleNamespace

        self.state = SimpleNamespace(
            current_task=None,
            last_builder_result=None,
            last_reviewer_result=None,
            status="waiting",
        )
        self.history = history

    def set_task(self, text: str) -> None:
        self.state.current_task = text.strip()


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

    def test_console_translation_keys_exist(self) -> None:
        console_path = Path(__file__).resolve().parents[1] / "agent_bridge" / "ui" / "console.py"
        console_source = console_path.read_text(encoding="utf-8")
        used_keys = set(re.findall(r"_t\([\"']([^\"']+)[\"']\)", console_source))

        self.assertTrue(used_keys)
        self.assertLessEqual(used_keys, set(TRANSLATIONS["en"]))
