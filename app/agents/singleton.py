"""Module-level orchestrator singleton — loaded once at app startup."""
from __future__ import annotations

from app.agents.orchestrator import AgentOrchestrator

_orchestrator: AgentOrchestrator | None = None


class AIUnavailableError(RuntimeError):
    """The AI layer is not ready (no LLM key, or the vector DB was unreachable at startup).

    Calculated features do not need the orchestrator, so this is reported per request (HTTP 503)
    instead of stopping the whole API from starting.
    """


def get_orchestrator() -> AgentOrchestrator:
    if _orchestrator is None:
        raise AIUnavailableError("The AI astrologer is not available right now.")
    return _orchestrator


def set_orchestrator(orc: AgentOrchestrator | None) -> None:
    global _orchestrator
    _orchestrator = orc


def is_ready() -> bool:
    return _orchestrator is not None
