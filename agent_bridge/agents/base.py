from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

AgentStreamCallback = Callable[[str, str], None]


@dataclass(slots=True)
class AgentResult:
    agent_name: str
    role: str
    prompt: str
    stdout: str
    stderr: str
    returncode: int
    duration_sec: float

    @property
    def text(self) -> str:
        return self.stdout.strip()


class AgentAdapter(Protocol):
    name: str
    role: str

    def run(self, prompt: str, stream_callback: AgentStreamCallback | None = None) -> AgentResult:
        ...
