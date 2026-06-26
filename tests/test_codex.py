from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase, mock

from agent_bridge.agents.codex import CodexAgent
from agent_bridge.config import Settings


class CodexAgentTests(TestCase):
    def test_run_adds_skip_git_repo_check_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            settings = Settings(project_dir=str(project_dir))
            agent = CodexAgent(role="builder", settings=settings)

            fake_result = mock.Mock(stdout="ok", stderr="", returncode=0, duration_sec=0.1)
            with mock.patch("agent_bridge.agents.codex.run_process", return_value=fake_result) as run_process:
                result = agent.run("build feature")

            self.assertEqual(result.stdout, "ok")
            run_process.assert_called_once()
            args, kwargs = run_process.call_args
            self.assertIn("--skip-git-repo-check", args[0])
            self.assertEqual(Path(kwargs["cwd"]).resolve(), project_dir.resolve())
