"""Compact text for the chart and dasha that go into LLM prompts.

The prompts used to embed the engine's pretty-printed JSON (about 6,500 characters, 2,000 tokens), most of it
raw longitudes, indices and scores the model never needs. This keeps every fact the answers rely on (signs, houses,
nakshatras, dignities, retrograde and combust flags, yogas with their meaning, dasha periods) in roughly a quarter of
the space, which matters because the LLM provider's free tier is limited by tokens per minute.
"""
from __future__ import annotations


def _num(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _month(value: object) -> str:
    return str(value)[:7] if value else "?"


def chart_to_text(chart: dict | None) -> str:
    if not chart:
        return "(no birth chart was provided)"
    lines: list[str] = []

    asc = chart.get("ascendant") or {}
    if asc:
        lines.append(f"Lagna: {asc.get('sign', '?')} {_num(asc.get('degree'))} deg, nakshatra {asc.get('nakshatra', '?')}, "
                     f"lord {asc.get('lord', '?')}")
    moon = chart.get("nakshatra_moon") or {}
    if moon:
        lines.append(f"Moon nakshatra: {moon.get('name', '?')} pada {moon.get('pada', '?')} (lord {moon.get('lord', '?')})")

    planets = chart.get("planets") or {}
    if planets:
        lines.append("Planets (sign, degree, house, nakshatra pada, status):")
        for name, p in planets.items():
            status = []
            dignity = p.get("dignity")
            if dignity and dignity != "neutral":
                status.append(str(dignity))
            if p.get("retrograde"):
                status.append("retrograde")
            if p.get("combust"):
                status.append("combust")
            suffix = f" [{', '.join(status)}]" if status else ""
            lines.append(f"- {name}: {p.get('sign', '?')} {_num(p.get('degree'))} deg, house {p.get('house', '?')}, "
                         f"{p.get('nakshatra', '?')} pada {p.get('nakshatra_pada', '?')} (lord {p.get('nakshatra_lord', '?')}){suffix}")

    houses = chart.get("houses") or []
    if houses:
        parts = []
        for h in houses:
            occupants = ", ".join(h.get("occupants") or []) or "empty"
            parts.append(f"{h.get('number')} {h.get('sign')} (lord {h.get('lord')}): {occupants}")
        lines.append("Houses: " + "; ".join(parts))

    yogas = chart.get("yogas") or []
    if yogas:
        lines.append("Yogas:")
        for y in yogas:
            if isinstance(y, dict):
                who = ", ".join(y.get("planets") or [])
                strength = y.get("strength")
                tail = f" [{who}{', ' if who and strength is not None else ''}{_num(strength, 2) if strength is not None else ''}]"
                lines.append(f"- {y.get('name', 'Yoga')}{tail}: {y.get('description', '')}".rstrip(": "))
            else:
                lines.append(f"- {y}")
    return "\n".join(lines)


def dasha_to_text(dasha: dict | None) -> str:
    if not dasha:
        return "(no dasha data)"
    parts = []
    for key, label in (("mahadasha", "Mahadasha"), ("antardasha", "Antardasha"), ("pratyantardasha", "Pratyantardasha")):
        period = dasha.get(key)
        if isinstance(period, dict):
            parts.append(f"{label} {period.get('lord', '?')} ({_month(period.get('start'))} to {_month(period.get('end'))})")
        elif period:
            parts.append(f"{label} {period}")
    return "; ".join(parts) or "(no dasha data)"
