"""
Agent state with write-permission control.

Each agent can only write to its authorized fields.
Violations raise immediately — fail loud.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Maps agent_name → set of fields it may write
_WRITE_PERMISSIONS: dict[str, set[str]] = {
    "intake":         {"birth_data", "errors"},
    "kundli":         {"chart", "dasha"},
    "rag":            {"retrieved_evidence"},
    "chart_analysis": {"analysis"},
    "dasha_analysis": {"dasha"},
    "transit":        {"transits"},
    "yoga":           {"analysis"},
    "topic":          {"topic", "analysis"},
    "rules":          {"rule_results"},
    "prediction":     {"analysis"},
    "verification":   {"verification"},
    "response":       {"final_response"},
}


@dataclass
class AstrologyState:
    """Single source of truth for one agent session."""
    request_id: str
    user_input: str
    birth_data: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    dasha: dict[str, Any] | None = None
    transits: dict[str, Any] | None = None
    topic: str | None = None
    retrieved_evidence: list[dict[str, Any]] = field(default_factory=list)
    rule_results: list[dict[str, Any]] = field(default_factory=list)
    analysis: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    final_response: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metadata.setdefault("started_at", datetime.now(timezone.utc).isoformat())

    def set(self, agent: str, field_name: str, value: Any) -> None:
        """Write-protected field setter. Raises PermissionError on violation."""
        allowed = _WRITE_PERMISSIONS.get(agent, set())
        if field_name not in allowed:
            raise PermissionError(
                f"Agent '{agent}' cannot write to field '{field_name}'. "
                f"Allowed: {sorted(allowed)}"
            )
        setattr(self, field_name, value)

    def append_error(self, error: str) -> None:
        self.errors.append(error)

    def append_analysis(self, item: dict[str, Any]) -> None:
        self.analysis.append(item)

    def append_evidence(self, agent: str, item: dict[str, Any]) -> None:
        if "rag" not in _WRITE_PERMISSIONS.get(agent, set()) and agent != "rag":
            raise PermissionError(f"Agent '{agent}' cannot write evidence")
        self.retrieved_evidence.append(item)
