from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import TestCase


class WrapperTests(TestCase):
    def test_agent_bridge_wrapper_runs_help(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / "agent-bridge"

        env = os.environ.copy()
        env["PROJECT_DIR"] = str(repo_root)

        completed = subprocess.run(
            [str(wrapper), "--help"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Usage:", completed.stdout)
