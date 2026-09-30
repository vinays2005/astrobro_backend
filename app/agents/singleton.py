"""Module-level orchestrator singleton — loaded once at app startup."""
from __future__ import annotations

from app.agents.orchestrator import AgentOrchestrator

_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    if _orchestrator is None:
        raise RuntimeError(
            "AgentOrchestrator not initialized. App startup may have failed."
        )
    return _orchestrator


def set_orchestrator(orc: AgentOrchestrator) -> None:
    global _orchestrator
    _orchestrator = orc
