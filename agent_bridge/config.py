from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


class SettingsError(RuntimeError):
    pass


class Settings(BaseModel):
    project_dir: str
    builder_agent: Literal["codex", "opencode"] = "codex"
    reviewer_agent: Literal["codex", "opencode"] = "opencode"
    codex_bin: str = "codex"
    opencode_bin: str = "opencode"
    codex_base_args: str = "exec"
    opencode_base_args: str = "run"
    opencode_builder_mode: str = "build"
    opencode_reviewer_mode: str = "plan"
    agent_timeout: int = 1800
    history_dir: str = ".agent-bridge/history"
    test_command: str = ""

    def project_path(self) -> Path:
        return Path(self.project_dir).expanduser().resolve()

    def history_path(self) -> Path:
        history_dir = Path(self.history_dir).expanduser()
        if history_dir.is_absolute():
            return history_dir
        return self.project_path() / history_dir


def load_settings() -> Settings:
    load_dotenv(override=False)
    raw = {
        "project_dir": _read_optional("PROJECT_DIR", str(Path.cwd())),
        "builder_agent": _read_required("BUILDER_AGENT", "codex"),
        "reviewer_agent": _read_required("REVIEWER_AGENT", "opencode"),
        "codex_bin": _read_required("CODEX_BIN", "codex"),
        "opencode_bin": _read_required("OPENCODE_BIN", "opencode"),
        "codex_base_args": _read_required("CODEX_BASE_ARGS", "exec"),
        "opencode_base_args": _read_required("OPENCODE_BASE_ARGS", "run"),
        "opencode_builder_mode": _read_required("OPENCODE_BUILDER_MODE", "build"),
        "opencode_reviewer_mode": _read_required("OPENCODE_REVIEWER_MODE", "plan"),
        "agent_timeout": _read_int("AGENT_TIMEOUT", 1800),
        "history_dir": _read_required("HISTORY_DIR", ".agent-bridge/history"),
        "test_command": _read_optional("TEST_COMMAND", ""),
    }

    try:
        settings = Settings(**raw)
    except ValidationError as exc:
        raise SettingsError(_format_validation_error(exc)) from exc

    project_path = settings.project_path()
    if not project_path.exists():
        raise SettingsError(f"PROJECT_DIR не существует: {project_path}")
    if not project_path.is_dir():
        raise SettingsError(f"PROJECT_DIR не является директорией: {project_path}")

    return settings


def _read_required(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SettingsError(f"Не задана обязательная переменная окружения {name}")
    return value


def _read_optional(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value or ""


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SettingsError(f"Переменная {name} должна быть целым числом, получено: {value!r}") from exc


def _format_validation_error(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = error.get("msg", "unknown error")
        messages.append(f"{location}: {message}")
    return "; ".join(messages) if messages else str(exc)
