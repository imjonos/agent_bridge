from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase

from agent_bridge.services.history import HistoryService


class HistoryTests(TestCase):
    def test_read_last_saved_task_returns_latest_task_created_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            first_file = history_dir / "2026-06-26_10-00-00.jsonl"
            second_file = history_dir / "2026-06-27_10-00-00.jsonl"
            first_file.write_text(
                json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            second_file.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "builder_result", "stdout": "ignored"}, ensure_ascii=False),
                        "{broken json",
                        json.dumps({"type": "task_created", "task": "new task"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            self.assertEqual(history.read_last_saved_task(), "new task")

    def test_read_last_saved_task_returns_none_without_saved_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                json.dumps({"type": "builder_result", "stdout": "ignored"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            self.assertIsNone(history.read_last_saved_task())

    def test_read_current_session_includes_last_workspace_records_on_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-26_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "new task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "new output"}, ensure_ascii=False),
                        json.dumps({"type": "reviewer_result", "stdout": "OK"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            records = history.read_current_session()
            self.assertEqual([record["type"] for record in records], ["task_created", "builder_result", "reviewer_result"])
            self.assertEqual(records[0]["task"], "new task")

    def test_task_cleared_suppresses_restore_from_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                        json.dumps({"type": "task_cleared"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            self.assertIsNone(history.read_last_saved_task())
            self.assertEqual(history.read_last_workspace_records(), [])

    def test_task_cleared_in_newer_file_suppresses_older_task_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-26_10-00-00.jsonl").write_text(
                json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                json.dumps({"type": "task_cleared"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            self.assertIsNone(history.read_last_saved_task())
            self.assertEqual(history.read_last_workspace_records(), [])

    def test_new_task_clears_startup_records_from_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            history = HistoryService(history_dir)

            history.append("task_created", {"task": "new task"})

            records = history.read_current_session()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["task"], "new task")

    def test_same_task_created_starts_clean_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            history = HistoryService(history_dir)

            history.append("task_created", {"task": "old task"})

            records = history.read_current_session()
            self.assertEqual([record["type"] for record in records], ["task_created"])
            self.assertEqual(records[0]["task"], "old task")

    def test_task_cleared_drops_startup_records_without_flushing_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            history = HistoryService(history_dir)

            history.append("task_cleared")

            session_records = [
                json.loads(line)
                for line in history.session_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["type"] for record in session_records], ["task_cleared"])

    def test_scan_last_workspace_records_falls_through_newer_file_without_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-26_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                        json.dumps({"type": "reviewer_result", "stdout": "OK"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                json.dumps({"type": "error", "message": "new file without task"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            history = HistoryService(history_dir)

            records = history.read_last_workspace_records()
            self.assertEqual([record["type"] for record in records], ["task_created", "builder_result", "reviewer_result"])
            self.assertEqual(records[0]["task"], "old task")

    def test_append_after_restore_without_new_task_continues_restored_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_dir = Path(tmp_dir)
            (history_dir / "2026-06-27_10-00-00.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"type": "task_created", "task": "old task"}, ensure_ascii=False),
                        json.dumps({"type": "builder_result", "stdout": "old output"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            history = HistoryService(history_dir)

            history.append("builder_result", {"stdout": "new output"})

            records = history.read_current_session()
            self.assertEqual([record["type"] for record in records], ["task_created", "builder_result", "builder_result"])
            self.assertEqual(records[1]["stdout"], "old output")
            self.assertEqual(records[2]["stdout"], "new output")

            session_records = [
                json.loads(line)
                for line in history.session_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["type"] for record in session_records], ["task_created", "builder_result", "builder_result"])

    def test_update_latest_result_tokens_persists_zero_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            history = HistoryService(Path(tmp_dir))
            history.append("task_created", {"task": "task"})
            history.append("builder_result", {"agent": "codex", "tokens": 125})

            history.update_latest_result_tokens({"builder_result"}, 0)

            records = history.read_current_session()
            self.assertEqual(records[-1]["tokens"], 0)
