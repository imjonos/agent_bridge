from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from agent_bridge.config import Settings, load_settings


class ConfigTests(TestCase):
    def test_load_settings_defaults_project_dir_to_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            with mock.patch("agent_bridge.config.load_dotenv", return_value=None), mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("agent_bridge.config.Path.cwd", return_value=project_dir):
                    settings = load_settings()

            self.assertEqual(settings.project_dir, str(project_dir))
            self.assertEqual(settings.builder_agent, "codex")
            self.assertEqual(settings.reviewer_agent, "opencode")

    def test_history_path_uses_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir), history_dir=".agent-bridge/history")
            self.assertEqual(settings.history_path(), project_dir.resolve() / ".agent-bridge" / "history")
