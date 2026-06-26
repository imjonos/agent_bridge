from __future__ import annotations

import shutil
from pathlib import Path

from .runner import run_shell_command


def get_git_status(project_dir: str) -> str:
    return _run_git_command(project_dir, "git status --short", "Git repository не найден")


def get_git_diff(project_dir: str) -> str:
    return _run_git_command(project_dir, "git diff", "Git repository не найден")


def _run_git_command(project_dir: str, command: str, missing_message: str) -> str:
    root = Path(project_dir)
    if shutil.which("git") is None:
        return "git не установлен"

    if not root.exists() or not root.is_dir():
        return f"Недоступна рабочая директория: {root}"

    probe = run_shell_command("git rev-parse --is-inside-work-tree", cwd=str(root), timeout=30)
    if probe.returncode != 0 or "true" not in probe.stdout.lower():
        return missing_message

    result = run_shell_command(command, cwd=str(root), timeout=30)
    if result.returncode != 0 and not result.stdout.strip():
        return result.stderr.strip() or f"Не удалось выполнить {command}"
    return result.stdout.strip() or "(empty)"
