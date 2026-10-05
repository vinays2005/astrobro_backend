"""Simple, explainable strength scores for planets and houses of a natal Chart (0-100)."""
from __future__ import annotations

BENEFICS = {"Jupiter", "Venus", "Mercury", "Moon"}
MALEFICS = {"Sun", "Mars", "Saturn", "Rahu", "Ketu"}
_DIGNITY_POINTS = {
    "exalted": 2.0, "moolatrikona": 1.5, "own": 1.5, "friendly": 0.5,
    "neutral": 0.0, "enemy": -1.0, "debilitated": -2.0,
}
_GOOD_HOUSES = {1, 4, 5, 7, 9, 10}
_DUSTHANA = {6, 8, 12}
_UPACHAYA = {3, 6, 10, 11}


def _clip(points: float) -> int:
    return int(max(5, min(98, round(50 + 10 * points))))


def planet_strength(chart, name: str) -> dict:
    """Dignity, house placement, combustion and retrogression folded into one score."""
    p = chart.planets.get(name)
    if p is None:
        return {"planet": name, "score": 50, "label": "unknown", "notes": []}
    pts = _DIGNITY_POINTS.get(p.dignity, 0.0)
    notes = [f"{p.dignity} in {p.sign}"]
    if p.house in _GOOD_HOUSES:
        pts += 1.0
        notes.append(f"well placed in the {p.house}th house")
    elif p.house in _DUSTHANA:
        pts -= 1.0
        notes.append(f"in a difficult house ({p.house}th)")
    if p.combust:
        pts -= 1.0
        notes.append("combust (too close to the Sun)")
    if p.retrograde and name not in ("Rahu", "Ketu"):
        notes.append("retrograde")
    score = _clip(pts)
    label = "strong" if score >= 62 else "weak" if score < 42 else "moderate"
    return {"planet": name, "score": score, "label": label, "dignity": p.dignity,
            "house": p.house, "notes": notes}


def house_strength(chart, house: int) -> dict:
    """Lord's dignity and placement, occupants and Jupiter's aspect on a house."""
    h = chart.houses[house - 1]
    lord = chart.planets.get(h.lord)
    pts, notes = 0.0, []
    if lord:
        pts += _DIGNITY_POINTS.get(lord.dignity, 0.0)
        notes.append(f"lord {h.lord} is {lord.dignity}")
        if lord.house in _GOOD_HOUSES:
            pts += 1.0
        elif lord.house in _DUSTHANA:
            pts -= 1.0
            notes.append(f"lord is placed in the {lord.house}th house")
        if lord.combust:
            pts -= 0.7
            notes.append("lord is combust")
    for occ in h.occupants:
        if occ in BENEFICS:
            pts += 0.7
            notes.append(f"{occ} supports the house")
        elif occ in MALEFICS:
            pts += 0.3 if house in _UPACHAYA else -0.7
            notes.append(f"{occ} occupies the house")
    if str(house) in chart.aspects.get("Jupiter", []):
        pts += 0.8
        notes.append("Jupiter aspects the house")
    score = _clip(pts)
    return {"house": house, "lord": h.lord, "sign": h.sign, "score": score,
            "label": "strong" if score >= 62 else "weak" if score < 42 else "moderate", "notes": notes}
