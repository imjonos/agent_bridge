from __future__ import annotations

import shlex

from ..config import Settings
from ..services.runner import run_process
from .base import AgentResult, AgentStreamCallback


class OpenCodeAgent:
    name = "opencode"

    def __init__(self, role: str, settings: Settings):
        self.role = role
        self.settings = settings

    def run(self, prompt: str, stream_callback: AgentStreamCallback | None = None) -> AgentResult:
        if not prompt.strip():
            return AgentResult(
                agent_name=self.name,
                role=self.role,
                prompt=prompt,
                stdout="",
                stderr="Пустой prompt",
                returncode=2,
                duration_sec=0.0,
            )

        agent_mode = self.settings.opencode_reviewer_mode if self.role == "reviewer" else self.settings.opencode_builder_mode
        args = [
            self.settings.opencode_bin,
            *shlex.split(self.settings.opencode_base_args),
            "--agent",
            agent_mode,
            prompt,
        ]
        result = run_process(
            args,
            cwd=str(self.settings.project_path()),
            timeout=self.settings.agent_timeout,
            stream_callback=stream_callback,
        )
        return AgentResult(
            agent_name=self.name,
            role=self.role,
            prompt=prompt,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            duration_sec=result.duration_sec,
        )
