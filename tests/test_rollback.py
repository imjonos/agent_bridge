from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

from agent_bridge.services.rollback import create_rollback_snapshot, rollback_last_snapshot


class RollbackTests(TestCase):
    def test_rollback_restores_dirty_files_and_removes_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            self._git(project_dir, "init")
            self._git(project_dir, "config", "user.email", "test@example.com")
            self._git(project_dir, "config", "user.name", "Test User")
            tracked = project_dir / "tracked.txt"
            untracked = project_dir / "notes.txt"
            created_by_agent = project_dir / "created.py"

            tracked.write_text("base\n", encoding="utf-8")
            self._git(project_dir, "add", "tracked.txt")
            self._git(project_dir, "commit", "-m", "initial")

            tracked.write_text("user change\n", encoding="utf-8")
            untracked.write_text("user note\n", encoding="utf-8")
            create_rollback_snapshot(str(project_dir), project_dir / ".agent-bridge" / "rollback")

            tracked.write_text("agent change\n", encoding="utf-8")
            untracked.write_text("agent note\n", encoding="utf-8")
            created_by_agent.write_text("print('agent')\n", encoding="utf-8")

            result = rollback_last_snapshot(str(project_dir), project_dir / ".agent-bridge" / "rollback")

            self.assertEqual(tracked.read_text(encoding="utf-8"), "user change\n")
            self.assertEqual(untracked.read_text(encoding="utf-8"), "user note\n")
            self.assertFalse(created_by_agent.exists())
            self.assertEqual(result.changed_count, 3)

    def test_rollback_reverts_clean_tracked_file_to_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            self._git(project_dir, "init")
            self._git(project_dir, "config", "user.email", "test@example.com")
            self._git(project_dir, "config", "user.name", "Test User")
            tracked = project_dir / "tracked.txt"

            tracked.write_text("base\n", encoding="utf-8")
            self._git(project_dir, "add", "tracked.txt")
            self._git(project_dir, "commit", "-m", "initial")

            create_rollback_snapshot(str(project_dir), project_dir / ".agent-bridge" / "rollback")
            tracked.write_text("agent change\n", encoding="utf-8")

            result = rollback_last_snapshot(str(project_dir), project_dir / ".agent-bridge" / "rollback")

            self.assertEqual(tracked.read_text(encoding="utf-8"), "base\n")
            self.assertEqual(result.reverted, ["tracked.txt"])

    @staticmethod
    def _git(project_dir: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=project_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
