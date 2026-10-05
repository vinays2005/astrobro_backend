"""Transits (Gochar): current positions, results from the natal Moon with Vedha, Sade Sati, events."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from app.astrology import ephem as E
from app.astrology.constants import COMBUSTION_ORBS, SIGNS

# Houses counted from the natal Moon in which each graha's transit is favourable
FAVOURABLE_HOUSES: dict[str, set[int]] = {
    "Sun": {3, 6, 10, 11},
    "Moon": {1, 3, 6, 7, 10, 11},
    "Mars": {3, 6, 11},
    "Mercury": {2, 4, 6, 8, 10, 11},
    "Jupiter": {2, 5, 7, 9, 11},
    "Venus": {1, 2, 3, 4, 5, 8, 9, 11, 12},
    "Saturn": {3, 6, 11},
    "Rahu": {3, 6, 11},
    "Ketu": {3, 6, 11},
}

# Vedha: a favourable transit in house H is obstructed by a planet occupying VEDHA[planet][H]
VEDHA_HOUSE: dict[str, dict[int, int]] = {
    "Sun": {3: 9, 6: 12, 10: 4, 11: 5},
    "Moon": {1: 5, 3: 9, 6: 12, 7: 2, 10: 4, 11: 8},
    "Mars": {3: 12, 6: 9, 11: 5},
    "Mercury": {2: 5, 4: 3, 6: 9, 8: 1, 10: 8, 11: 12},
    "Jupiter": {2: 12, 5: 4, 7: 3, 9: 10, 11: 8},
    "Venus": {1: 8, 2: 7, 3: 1, 4: 10, 5: 9, 8: 5, 9: 11, 11: 6, 12: 3},
    "Saturn": {3: 12, 6: 9, 11: 5},
}
_VEDHA_EXEMPT = {("Sun", "Saturn"), ("Saturn", "Sun"), ("Moon", "Mercury"), ("Mercury", "Moon")}
_VEDHA_CAUSERS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")

_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th", 7: "7th",
        8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th"}

_GOOD = {
    "Sun": "vitality, confidence and recognition",
    "Moon": "emotional ease and support from others",
    "Mars": "energy, courage and decisive action",
    "Mercury": "clear thinking, communication and quick gains",
    "Jupiter": "wisdom, optimism and good fortune",
    "Venus": "harmony, affection and comfort",
    "Saturn": "discipline, steady progress and earned rewards",
    "Rahu": "unconventional openings and sudden opportunities",
    "Ketu": "detachment, insight and freedom from clutter",
}
_BAD = {
    "Sun": "ego friction, heat and pressure from authority",
    "Moon": "mood swings and sensitivity",
    "Mars": "impatience, arguments and a risk of accidents",
    "Mercury": "scattered thinking and miscommunication",
    "Jupiter": "overconfidence, overspending and ignored advice",
    "Venus": "indulgence and friction in relationships",
    "Saturn": "delays, heaviness and extra responsibility",
    "Rahu": "confusion, restlessness and risky shortcuts",
    "Ketu": "withdrawal, uncertainty and sudden detachment",
}
_THEME = {
    1: "your health and self-image", 2: "money, speech and family",
    3: "effort, courage and siblings", 4: "home, mother and peace of mind",
    5: "creativity, romance and children", 6: "work routine, health and rivals",
    7: "partnerships and marriage", 8: "sudden changes, secrets and shared money",
    9: "luck, mentors and long journeys", 10: "career and public standing",
    11: "gains, income and friendships", 12: "expenses, rest and foreign matters",
}

# Daily mood of the transiting Moon by house from the natal Moon
MOON_DAILY = {
    1: "Emotions run strong and you feel the spotlight on yourself. Look after your health and avoid snap decisions.",
    2: "Money and family conversations come to the front. Watch what you say and avoid impulsive spending.",
    3: "Courage and initiative are high. A good day for short trips, calls and pushing a pending task forward.",
    4: "You crave home comforts and peace of mind. Time with family helps; avoid conflict over property or vehicles.",
    5: "Creativity, romance and fun are favoured. A good day for children, study and playful ideas.",
    6: "Competitors and chores need attention, but you can outwork obstacles. Mind your digestion and routine.",
    7: "Partnerships take centre stage. A favourable day to meet people, negotiate and strengthen a relationship.",
    8: "Mood is intense and plans may change suddenly. Avoid risks, keep secrets safe and stay patient.",
    9: "Optimism and luck support you. Good for learning, advice from elders and spiritual practice.",
    10: "Professional matters get a lift and others notice your work. A strong day to take responsibility.",
    11: "Gains, friends and old promises bring pleasant news. A good day to network and collect dues.",
    12: "Energy dips and expenses rise. Rest, retreat and quiet reflection serve you better than big moves.",
}

SADE_SATI_PHASES = {11: "Rising (Saturn in 12th from Moon)", 0: "Peak (Saturn over the Moon)",
                    1: "Setting (Saturn in 2nd from Moon)"}


# ── Current transits ──────────────────────────────────────────────────────────

def current_transits(when: datetime | None = None) -> dict:
    """Positions of all nine grahas at an instant, with combustion flags."""
    when = when or datetime.now(timezone.utc)
    jd = E.to_jd(when)
    pos = E.positions(jd)
    sun_lon = pos["Sun"]["longitude"]
    out = []
    for name in E.PLANETS:
        p = dict(pos[name])
        p["name"] = name
        orb = COMBUSTION_ORBS.get(name)
        if orb and name != "Sun":
            diff = abs(p["longitude"] - sun_lon) % 360
            diff = 360 - diff if diff > 180 else diff
            p["combust"] = diff <= orb
        else:
            p["combust"] = False
        out.append(p)
    return {"timestamp": when.astimezone(timezone.utc).isoformat(), "planets": out}


# ── Gochar from the natal Moon ────────────────────────────────────────────────

def house_from(sign_idx: int, ref_sign_idx: int) -> int:
    return ((sign_idx - ref_sign_idx) % 12) + 1


def gochar(pos: dict[str, dict], ref_sign_idx: int) -> dict[str, dict]:
    """Per-planet transit house, favourability and Vedha status relative to a reference sign."""
    houses = {p: house_from(pos[p]["sign_index"], ref_sign_idx) for p in E.PLANETS}
    out: dict[str, dict] = {}
    for p in E.PLANETS:
        h = houses[p]
        favourable = h in FAVOURABLE_HOUSES[p]
        blocker = None
        vh = VEDHA_HOUSE.get(p, {}).get(h) if favourable else None
        if vh:
            for q in _VEDHA_CAUSERS:
                if q != p and (p, q) not in _VEDHA_EXEMPT and houses[q] == vh:
                    blocker = q
                    break
        # An unfavourable transit weighs less than a favourable one: most houses are unfavourable
        value = 1.0 if favourable and not blocker else 0.2 if blocker else -0.5
        out[p] = {
            "planet": p, "house": h, "sign": pos[p]["sign"],
            "favourable": favourable, "obstructed_by": blocker, "value": value,
            "retrograde": pos[p]["retrograde"],
            "text": describe(p, h, favourable, blocker, pos[p]["retrograde"]),
        }
    return out


def describe(planet: str, house: int, favourable: bool, blocker: str | None, retro: bool) -> str:
    if planet == "Moon":
        return MOON_DAILY[house]
    where = f"{planet} in your {_ORD[house]} house"
    if blocker:
        text = f"{where} is normally helpful, but {blocker} obstructs it (Vedha), so the results are muted."
    elif favourable:
        text = f"{where} brings {_GOOD[planet]} to {_THEME[house]}."
    else:
        text = f"{where} brings {_BAD[planet]} to {_THEME[house]}."
    if retro:
        text += " Being retrograde, its results turn inward and may arrive late."
    return text


# ── Sade Sati / Dhaiya ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _saturn_ingresses_all() -> tuple[dict, ...]:
    """Every Saturn sign change from 1900 to 2200, computed once (fixed astronomy)."""
    jd0 = E.to_jd(datetime(1900, 1, 1, tzinfo=timezone.utc))
    jd1 = E.to_jd(datetime(2200, 1, 1, tzinfo=timezone.utc))
    return tuple(E.ingresses("Saturn", jd0, jd1))


def saturn_intervals(jd_start: float, jd_end: float) -> list[tuple[float, float, int]]:
    """Intervals (start_jd, end_jd, saturn_sign_index) covering [jd_start, jd_end]."""
    sign = E.sign_index(E.lon_speed(jd_start, "Saturn")[0])
    intervals: list[tuple[float, float, int]] = []
    t = jd_start
    for ev in _saturn_ingresses_all():
        if ev["jd"] <= jd_start or ev["jd"] >= jd_end:
            continue
        intervals.append((t, ev["jd"], sign))
        t, sign = ev["jd"], ev["to_sign_index"]
    intervals.append((t, jd_end, sign))
    return intervals


def _merge(intervals: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    merged: list[list] = []
    for s, e, label in intervals:
        if merged and merged[-1][2] == label and abs(merged[-1][1] - s) < 1e-6:
            merged[-1][1] = e
        else:
            merged.append([s, e, label])
    return [(a, b, c) for a, b, c in merged]


def sade_sati_timeline(moon_sign_idx: int, around: datetime | None = None, span_years: int = 35) -> dict:
    """Sade Sati phases, Dhaiya (4th/8th) periods and the current status around a date."""
    around = around or datetime.now(timezone.utc)
    jd_now = E.to_jd(around)
    jd0, jd1 = jd_now - span_years * 365.25, jd_now + span_years * 365.25
    labelled: list[tuple[float, float, str]] = []
    for s, e, sign in saturn_intervals(jd0, jd1):
        offset = (sign - moon_sign_idx) % 12
        if offset in SADE_SATI_PHASES:
            labelled.append((s, e, f"sade_sati:{SADE_SATI_PHASES[offset]}"))
        elif offset == 3:
            labelled.append((s, e, "dhaiya:Kantaka Shani (Saturn in 4th from Moon)"))
        elif offset == 7:
            labelled.append((s, e, "dhaiya:Ashtama Shani (Saturn in 8th from Moon)"))
    periods = []
    for s, e, label in _merge(labelled):
        kind, _, phase = label.partition(":")
        periods.append({
            "type": kind, "phase": phase,
            "start": E.from_jd(s).date().isoformat(), "end": E.from_jd(e).date().isoformat(),
            "current": s <= jd_now <= e,
        })
    current = next((p for p in periods if p["current"]), None)
    return {
        "moon_sign": SIGNS[moon_sign_idx],
        "current": current,
        "active": current is not None,
        "periods": [p for p in periods
                    if p["end"] >= E.from_jd(jd_now - 365.25 * 10).date().isoformat()
                    and p["start"] <= E.from_jd(jd_now + 365.25 * 25).date().isoformat()],
    }


# ── Events (ingress / retrograde) ─────────────────────────────────────────────

SLOW = ("Saturn", "Jupiter", "Rahu", "Ketu")
FAST = ("Sun", "Mars", "Mercury", "Venus")


def upcoming_events(
    start: datetime, days: int, planets: tuple[str, ...] | None = None, moon_events: bool = True
) -> list[dict]:
    """Sign ingresses and retrograde/direct stations in a window, soonest first."""
    planets = planets or ("Saturn", "Jupiter", "Rahu", "Mars", "Venus", "Mercury", "Sun")
    jd0 = E.to_jd(start)
    jd1 = jd0 + days
    events: list[dict] = []
    for name in planets:
        for ev in E.ingresses(name, jd0, jd1):
            events.append({
                "type": "ingress", "planet": name, "jd": ev["jd"],
                "from_sign": ev["from_sign"], "to_sign": ev["to_sign"],
                "to_sign_index": ev["to_sign_index"], "retrograde": ev["retrograde"],
                "title": f"{name} enters {ev['to_sign']}" + (" (retrograde)" if ev["retrograde"] else ""),
            })
        for ev in E.stations(name, jd0, jd1):
            events.append({
                "type": ev["type"], "planet": name, "jd": ev["jd"], "sign": ev["sign"],
                "title": f"{name} turns {'retrograde' if ev['type'] == 'retrograde_start' else 'direct'} in {ev['sign']}",
            })
    for jd in (E.lunations(jd0, jd1, 0.0) if moon_events else []):
        events.append({"type": "new_moon", "planet": "Moon", "jd": jd, "title": "New Moon (Amavasya)",
                       "sign": SIGNS[E.sign_index(E.lon_speed(jd, "Moon")[0])]})
    for jd in (E.lunations(jd0, jd1, 180.0) if moon_events else []):
        events.append({"type": "full_moon", "planet": "Moon", "jd": jd, "title": "Full Moon (Purnima)",
                       "sign": SIGNS[E.sign_index(E.lon_speed(jd, "Moon")[0])]})
    events.sort(key=lambda e: e["jd"])
    return events


def event_to_dict(ev: dict, tz: str) -> dict:
    out = {k: v for k, v in ev.items() if k != "jd"}
    out["when"] = E.jd_to_local(ev["jd"], tz).isoformat()
    return out
