from __future__ import annotations

from ..config import Settings
from .base import AgentAdapter
from .codex import CodexAgent
from .opencode import OpenCodeAgent


def create_agent(agent_type: str, role: str, settings: Settings) -> AgentAdapter:
    if agent_type == "codex":
        return CodexAgent(role=role, settings=settings)

    if agent_type == "opencode":
        return OpenCodeAgent(role=role, settings=settings)

    raise ValueError(f"Unsupported agent type: {agent_type}")
