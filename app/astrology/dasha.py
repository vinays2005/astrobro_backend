"""Vimshottari Dasha timeline (Maha > Antar > Pratyantar) with chart-specific interpretation."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.astrology.constants import (
    DASHA_SEQUENCE,
    DASHA_YEARS,
    HOUSE_SIGNIFICATIONS,
    SIGN_LORDS,
    SIGNS,
)

YEAR_DAYS = 365.25

_PLANET_NATURE = {
    "Sun": "authority, vitality, father and recognition",
    "Moon": "mind, mother, emotions and public support",
    "Mars": "energy, courage, property and conflict",
    "Mercury": "intellect, trade, communication and skills",
    "Jupiter": "wisdom, growth, children, teachers and good fortune",
    "Venus": "love, comforts, arts, vehicles and partnership",
    "Saturn": "discipline, hard work, delay and long-term results",
    "Rahu": "ambition, foreign links, unconventional gains and illusion",
    "Ketu": "detachment, spirituality, research and sudden endings",
}
_MAHA_FLAVOUR = {
    "Ketu": "A phase of detachment and inner search; worldly results are uneven but spiritual insight grows.",
    "Venus": "A phase of relationships, comfort and creativity; material pleasures and partnerships take centre stage.",
    "Sun": "A phase of authority and self-expression; recognition, government matters and leadership come forward.",
    "Moon": "A phase of emotional growth and public life; the mind, home and nurturing themes dominate.",
    "Mars": "A phase of drive and action; courage, property and competition are active, and patience is tested.",
    "Rahu": "A phase of ambition and change; foreign links and unconventional paths bring gains and confusion in turn.",
    "Jupiter": "A phase of growth and wisdom; learning, children, mentors and good fortune are emphasised.",
    "Saturn": "A phase of discipline and responsibility; results come slowly but steadily through sustained effort.",
    "Mercury": "A phase of learning, business and communication; skills, trade and networking flourish.",
}


def build_timeline(moon_lon: float, birth_dt: datetime) -> list[dict]:
    """Nine Mahadashas from birth, each with its nine Antardashas."""
    nak_span = 360.0 / 27.0
    nak_idx = int(moon_lon / nak_span) % 27
    lord_idx = nak_idx % 9
    elapsed = (moon_lon % nak_span) / nak_span

    out: list[dict] = []
    start = birth_dt
    for i in range(9):
        lord = DASHA_SEQUENCE[(lord_idx + i) % 9]
        full = DASHA_YEARS[lord]
        years = full * (1 - elapsed) if i == 0 else float(full)
        end = start + timedelta(days=years * YEAR_DAYS)
        out.append({
            "lord": lord, "start": start, "end": end, "years": round(years, 3),
            "balance_at_birth": i == 0,
            "antardashas": _antardashas(lord, start, end, full, partial=(i == 0), elapsed=elapsed),
        })
        start = end
    return out


def _antardashas(maha: str, start: datetime, end: datetime, full_years: int, partial: bool, elapsed: float) -> list[dict]:
    """Sub-periods inside a Mahadasha; the first (birth) Mahadasha is cut mid-way."""
    full_start = start - timedelta(days=full_years * elapsed * YEAR_DAYS) if partial else start
    maha_idx = DASHA_SEQUENCE.index(maha)
    out = []
    cursor = full_start
    for i in range(9):
        lord = DASHA_SEQUENCE[(maha_idx + i) % 9]
        length = timedelta(days=full_years * YEAR_DAYS * DASHA_YEARS[lord] / 120.0)
        a_start, a_end = cursor, cursor + length
        cursor = a_end
        if a_end <= start:
            continue
        out.append({"lord": lord, "start": max(a_start, start), "end": min(a_end, end)})
    return out


def pratyantardashas(maha: str, antar: str, a_start: datetime, a_end: datetime) -> list[dict]:
    total = (a_end - a_start).total_seconds()
    idx = DASHA_SEQUENCE.index(antar)
    cursor = a_start
    out = []
    for i in range(9):
        lord = DASHA_SEQUENCE[(idx + i) % 9]
        length = total * DASHA_YEARS[lord] / 120.0
        end = cursor + timedelta(seconds=length)
        out.append({"lord": lord, "start": cursor, "end": min(end, a_end)})
        cursor = end
    return out


def period_at(timeline: list[dict], when: datetime) -> dict | None:
    for maha in timeline:
        if maha["start"] <= when < maha["end"]:
            antar = next((a for a in maha["antardashas"] if a["start"] <= when < a["end"]), None)
            praty = None
            if antar:
                praty = next((p for p in pratyantardashas(maha["lord"], antar["lord"], antar["start"], antar["end"])
                              if p["start"] <= when < p["end"]), None)
            return {"maha": maha, "antar": antar, "praty": praty}
    return None


# ── Chart-specific interpretation ─────────────────────────────────────────────

def lord_profile(planet: str, planets: dict, houses: list, asc_sign_idx: int) -> dict:
    """Which houses a planet rules and where it sits in this chart."""
    ruled = [((i - asc_sign_idx) % 12) + 1 for i, lord in enumerate(SIGN_LORDS) if lord == planet]
    p = planets.get(planet)
    return {
        "planet": planet,
        "rules_houses": sorted(ruled),
        "placed_house": p.house if p else None,
        "placed_sign": p.sign if p else None,
        "dignity": p.dignity if p else None,
        "retrograde": bool(p.retrograde) if p else False,
    }


def _ord(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def interpret(planet: str, profile: dict, level: str = "mahadasha") -> str:
    ruled = profile["rules_houses"]
    parts = []
    if level == "mahadasha":
        parts.append(_MAHA_FLAVOUR[planet])
    if ruled:
        themes = "; ".join(
            " and ".join(x.strip() for x in HOUSE_SIGNIFICATIONS[h].split(",")[:2]) for h in ruled
        )
        noun = "houses" if len(ruled) > 1 else "house"
        parts.append(f"{planet} rules your {' and '.join(_ord(h) for h in ruled)} {noun} ({themes}), "
                     "so those areas are activated.")
    if profile["placed_house"]:
        parts.append(f"It sits in your {_ord(profile['placed_house'])} house in {profile['placed_sign']}"
                     f" ({profile['dignity']}), colouring the period with {_PLANET_NATURE[planet]}.")
    if profile["retrograde"]:
        parts.append("Being retrograde, its results often arrive late or after a review of past matters.")
    return " ".join(parts)


def period_dict(p: dict, with_text: bool = False, profile: dict | None = None, level: str = "mahadasha") -> dict:
    out = {"lord": p["lord"], "start": p["start"].date().isoformat(), "end": p["end"].date().isoformat()}
    if "years" in p:
        out["years"] = p["years"]
    if with_text and profile is not None:
        out["interpretation"] = interpret(p["lord"], profile, level)
    return out


def sign_name(idx: int) -> str:
    return SIGNS[idx % 12]
