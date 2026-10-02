"""
Prompt injection defense for retrieved document content.

Retrieved text is UNTRUSTED DATA — never instructions.
Every chunk entering the LLM context is sanitized and wrapped in DATA delimiters.
"""
from __future__ import annotations

import re

# Patterns that indicate injection attempts
_INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(previous|above|all)\s+instructions",
    r"forget\s+(everything|all|previous)",
    r"you\s+are\s+now\s+",
    r"new\s+instructions",
    r"system\s*:\s*",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"###\s*(instruction|system|human|assistant)",
    r"disregard\s+.*instructions",
    r"override\s+.*prompt",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def sanitize_text(text: str, max_length: int = 2000) -> str:
    """Remove injection patterns and truncate."""
    if not text:
        return ""
    text = text[:max_length]
    for pattern in _COMPILED:
        text = pattern.sub("[REDACTED]", text)
    return text


def wrap_as_data(text: str, source: dict[str, object]) -> str:
    """
    Wrap retrieved chunk in DATA delimiters so the LLM treats it as
    reference material — never as instructions.
    """
    clean = sanitize_text(text)
    book = source.get("book", "unknown")
    page = source.get("page", "")
    return (
        f'<RETRIEVED_DATA source="{book}" page="{page}">\n'
        f"{clean}\n"
        f"</RETRIEVED_DATA>"
    )


def wrap_evidence_list(chunks: list[dict[str, object]]) -> str:
    """Wrap a list of retrieved chunks for inclusion in a prompt."""
    if not chunks:
        return "<RETRIEVED_DATA>No relevant book evidence found.</RETRIEVED_DATA>"
    parts = [wrap_as_data(str(c.get("text", "")), c.get("metadata", c)) for c in chunks]
    return "\n\n".join(parts)
