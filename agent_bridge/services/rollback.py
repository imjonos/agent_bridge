from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class RollbackError(RuntimeError):
    pass


@dataclass(slots=True)
class RollbackSnapshot:
    snapshot_id: str
    files_count: int


@dataclass(slots=True)
class RollbackResult:
    snapshot_id: str
    restored: list[str]
    removed: list[str]
    reverted: list[str]

    @property
    def changed_count(self) -> int:
        return len(set(self.restored + self.removed + self.reverted))


def create_rollback_snapshot(project_dir: str, rollback_dir: str | Path) -> RollbackSnapshot:
    root = _git_root(project_dir)
    base_dir = Path(rollback_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    snapshot_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    snapshot_dir = base_dir / snapshot_id
    files_dir = snapshot_dir / "files"
    files_dir.mkdir(parents=True)

    entries = _status_entries(root)
    metadata_entries: dict[str, dict[str, Any]] = {}
    files_count = 0
    for path, status in entries.items():
        absolute_path = root / path
        saved_name = _saved_name(path)
        entry: dict[str, Any] = {"status": status, "exists": absolute_path.is_file()}
        if absolute_path.is_file():
            shutil.copy2(absolute_path, files_dir / saved_name)
            entry["saved_name"] = saved_name
            files_count += 1
        metadata_entries[path] = entry

    metadata = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "entries": metadata_entries,
    }
    (snapshot_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (base_dir / "last.json").write_text(json.dumps({"snapshot_id": snapshot_id}, ensure_ascii=False), encoding="utf-8")
    return RollbackSnapshot(snapshot_id=snapshot_id, files_count=files_count)


def rollback_last_snapshot(project_dir: str, rollback_dir: str | Path) -> RollbackResult:
    root = _git_root(project_dir)
    base_dir = Path(rollback_dir)
    last_file = base_dir / "last.json"
    if not last_file.exists():
        raise RollbackError("Нет снимка для отката")

    snapshot_id = str(json.loads(last_file.read_text(encoding="utf-8")).get("snapshot_id", ""))
    if not snapshot_id:
        raise RollbackError("Некорректный файл последнего снимка отката")

    snapshot_dir = base_dir / snapshot_id
    metadata_file = snapshot_dir / "metadata.json"
    if not metadata_file.exists():
        raise RollbackError(f"Снимок отката не найден: {snapshot_id}")

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    before_entries: dict[str, dict[str, Any]] = dict(metadata.get("entries", {}))
    current_entries = _status_entries(root)
    paths = sorted(set(before_entries) | set(current_entries))

    restored: list[str] = []
    removed: list[str] = []
    reverted: list[str] = []
    for path in paths:
        before = before_entries.get(path)
        if before is not None:
            _restore_snapshot_path(root, snapshot_dir, path, before)
            restored.append(path)
            continue

        if _is_tracked(root, path):
            _run_git(root, ["reset", "--", path])
            _run_git(root, ["checkout", "--", path])
            reverted.append(path)
            continue

        _remove_worktree_path(root / path)
        removed.append(path)

    return RollbackResult(snapshot_id=snapshot_id, restored=restored, removed=removed, reverted=reverted)


def _restore_snapshot_path(root: Path, snapshot_dir: Path, path: str, entry: dict[str, Any]) -> None:
    _run_git(root, ["reset", "--", path], check=False)
    if entry.get("exists") and entry.get("saved_name"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_dir / "files" / str(entry["saved_name"]), target)
        return
    _remove_worktree_path(root / path)


def _status_entries(root: Path) -> dict[str, str]:
    result = _run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    entries: dict[str, str] = {}
    parts = [part for part in result.stdout.split("\0") if part]
    index = 0
    while index < len(parts):
        item = parts[index]
        status = item[:2]
        path = item[3:]
        if status.startswith("R") or status.startswith("C"):
            index += 1
            if index >= len(parts):
                break
            path = parts[index]
        if not _is_internal_path(path):
            entries[path] = status
        index += 1
    return entries


def _git_root(project_dir: str) -> Path:
    root = Path(project_dir).expanduser()
    if not root.exists() or not root.is_dir():
        raise RollbackError(f"Недоступна рабочая директория: {root}")
    result = _run_git(root, ["rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        raise RollbackError("Git repository не найден")
    return Path(result.stdout.strip())


def _is_tracked(root: Path, path: str) -> bool:
    return _run_git(root, ["ls-files", "--error-unmatch", "--", path], check=False).returncode == 0


def _remove_worktree_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _saved_name(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _is_internal_path(path: str) -> bool:
    return path == ".agent-bridge" or path.startswith(".agent-bridge/")


def _run_git(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"Не удалось выполнить git {' '.join(args)}"
        raise RollbackError(message)
    return result
