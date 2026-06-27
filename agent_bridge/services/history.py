from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryService:
    def __init__(self, history_dir: str):
        self.history_dir = Path(history_dir).expanduser()
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        self.session_file = self.history_dir / f"{self.session_id}.jsonl"
        self._lock = threading.Lock()
        self._startup_records = self._scan_last_workspace_records()

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            if event_type == "task_created":
                self._startup_records = []
            elif event_type == "task_cleared":
                self._startup_records = []
            elif self._startup_records:
                self._write_records(self._startup_records)
                self._startup_records = []
            record = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "type": event_type,
            }
            if payload:
                record.update(payload)
            self._write_records([record])

    def update_latest_result_tokens(self, event_types: set[str], tokens: int) -> None:
        with self._lock:
            if tokens < 0 or not self.session_file.exists():
                return
            records = self._read_records(self.session_file)
            for index in range(len(records) - 1, -1, -1):
                if records[index].get("type") in event_types:
                    records[index]["tokens"] = tokens
                    self._replace_records(records)
                    return

    def _write_records(self, records: list[dict[str, Any]]) -> None:
        with self.session_file.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _replace_records(self, records: list[dict[str, Any]]) -> None:
        tmp_file = self.session_file.with_name(f".{self.session_file.name}.tmp")
        try:
            tmp_file.write_text(
                "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
                encoding="utf-8",
            )
            tmp_file.replace(self.session_file)
        finally:
            tmp_file.unlink(missing_ok=True)

    def read_current_session(self) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._startup_records)
            if not self.session_file.exists():
                return records
            with self.session_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        records.append(
                            {
                                "timestamp": "",
                                "type": "error",
                                "message": f"Невозможно разобрать запись истории: {line[:120]}",
                            }
                        )
            return records

    def read_last_workspace_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._startup_records)

    def _scan_last_workspace_records(self) -> list[dict[str, Any]]:
        for history_file in sorted(self.history_dir.glob("*.jsonl"), reverse=True):
            records = self._read_records(history_file)
            for index in range(len(records) - 1, -1, -1):
                record = records[index]
                event_type = record.get("type")
                if event_type == "task_cleared":
                    return []
                if event_type == "task_created":
                    task = record.get("task")
                    return records[index:] if isinstance(task, str) and task.strip() else []
        return []

    def read_last_saved_task(self) -> str | None:
        with self._lock:
            records = self._startup_records
            if not records:
                return None
            task = records[0].get("task")
            return task if isinstance(task, str) and task.strip() else None

    @staticmethod
    def _parse_record(line: str) -> dict[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def _read_records(self, history_file: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with history_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                record = self._parse_record(line)
                if record is not None:
                    records.append(record)
        return records
