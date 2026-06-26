from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryService:
    def __init__(self, history_dir: str):
        self.history_dir = Path(history_dir).expanduser()
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_file = self.history_dir / f"{self.session_id}.jsonl"

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
        }
        if payload:
            record.update(payload)
        with self.session_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_current_session(self) -> list[dict[str, Any]]:
        if not self.session_file.exists():
            return []
        records: list[dict[str, Any]] = []
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
