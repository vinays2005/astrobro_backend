"""Daily / weekly / monthly / yearly horoscopes from Moon-sign Gochar. Fully deterministic.

A horoscope is looked up by *Moon sign* (Rashi). Scores come from classical Gochar results
(favourable houses from the Moon, with Vedha) weighted per life area; wording comes from fixed text banks.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from app.astrology import ephem as E
from app.astrology import transits as T
from app.astrology.constants import SIGN_LORDS, SIGNS

SIGN_ALIASES: dict[str, int] = {}
for _i, _names in enumerate([
    ("aries", "mesha", "mesh"), ("taurus", "vrishabha", "vrishab", "vrish"),
    ("gemini", "mithuna", "mithun"), ("cancer", "karka", "kark"), ("leo", "simha", "singh"),
    ("virgo", "kanya"), ("libra", "tula"), ("scorpio", "vrischika", "vrishchik", "vrishchika"),
    ("sagittarius", "dhanu", "dhanus"), ("capricorn", "makara", "makar"),
    ("aquarius", "kumbha", "kumbh"), ("pisces", "meena", "meen"),
]):
    for _n in _names:
        SIGN_ALIASES[_n] = _i

ELEMENTS = ["Fire", "Earth", "Air", "Water"] * 3
AREAS = ("love", "career", "finance", "health", "family")
_AREA_WEIGHTS: dict[str, dict[str, float]] = {
    "love": {"Venus": 3, "Moon": 2, "Mars": 1, "Jupiter": 1, "Rahu": 1},
    "career": {"Sun": 2, "Saturn": 2, "Jupiter": 2, "Mercury": 1, "Mars": 1},
    "finance": {"Jupiter": 3, "Mercury": 2, "Venus": 1, "Moon": 1, "Rahu": 1},
    "health": {"Sun": 2, "Moon": 2, "Mars": 2, "Saturn": 1, "Ketu": 1},
    "family": {"Moon": 2, "Jupiter": 2, "Venus": 1, "Mercury": 1, "Saturn": 1},
}
_OVERALL_WEIGHTS = {"Moon": 3, "Jupiter": 2, "Saturn": 2, "Sun": 1, "Mars": 1,
                    "Mercury": 1, "Venus": 1, "Rahu": 1, "Ketu": 1}

_NUMBER = {"Sun": 1, "Moon": 2, "Jupiter": 3, "Rahu": 4, "Mercury": 5,
           "Venus": 6, "Ketu": 7, "Saturn": 8, "Mars": 9}
_COLOUR = {"Sun": "Saffron", "Moon": "White", "Mars": "Red", "Mercury": "Green",
           "Jupiter": "Yellow", "Venus": "Pink", "Saturn": "Dark Blue"}
_DAY_LORD = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]  # Sunday first

_TEXT: dict[str, dict[str, list[str]]] = {
    "love": {
        "pos": ["Affection flows easily {when} — a good moment to express feelings or deepen a bond.",
                "Warmth and charm are on your side {when}; conversations with loved ones feel sweet.",
                "Romantic energy is supportive {when}: plan something thoughtful for someone you care about."],
        "mid": ["Relationships run steady {when}; small gestures matter more than big declarations.",
                "Love is calm and neutral {when} — listen more than you speak.",
                "No big shifts in love {when}; keep communication open and expectations realistic."],
        "neg": ["Misunderstandings can creep into relationships {when}; pause before reacting.",
                "Emotions may feel heavy {when} — avoid raising old issues with a partner.",
                "Patience is needed in matters of the heart {when}; give space instead of pushing."],
    },
    "career": {
        "pos": ["Work gets a boost {when} — your efforts are noticed, so take the lead on something important.",
                "Productive energy helps you finish tasks and impress seniors {when}.",
                "A good time {when} to pitch ideas, negotiate or begin a new assignment."],
        "mid": ["A steady stretch at work {when}; routine tasks move forward without drama.",
                "Focus on details and finish pending work {when} rather than starting new projects.",
                "Progress is gradual {when}; consistency will serve you better than speed."],
        "neg": ["Delays or friction at work are possible {when}; double-check details and avoid office politics.",
                "Pressure from deadlines may feel heavy {when} — prioritise and ask for help.",
                "Hold off on big career decisions {when}; a calmer phase will serve them better."],
    },
    "finance": {
        "pos": ["Money matters look favourable {when} — good for collecting dues or planning savings.",
                "Gains or useful financial news are indicated {when}; stay disciplined with the extra.",
                "Smart financial choices come easily {when}; consider long-term plans."],
        "mid": ["Finances are stable {when}; stick to your budget and avoid impulse purchases.",
                "Neither big gains nor losses are indicated {when}; review your accounts calmly.",
                "A time for routine money management {when} rather than new investments."],
        "neg": ["Expenses may exceed expectations {when} — avoid lending, speculation and big purchases.",
                "Financial caution is advised {when}; read the fine print before committing.",
                "Unplanned costs could appear {when}; keep a buffer and delay risky decisions."],
    },
    "health": {
        "pos": ["Energy and vitality are good {when} — a great time to exercise or start a healthy habit.",
                "You feel light and resilient {when}; keep your routine and stay hydrated.",
                "Body and mind are in sync {when}; use the energy wisely."],
        "mid": ["Health is steady {when}; keep regular meals and sleep.",
                "Minor tiredness is possible {when} — balance work with rest.",
                "Nothing alarming {when}; gentle movement will keep you comfortable."],
        "neg": ["Energy dips are likely {when} — rest, hydrate and avoid overexertion.",
                "Stress may affect sleep or digestion {when}; slow down and eat light.",
                "Take extra care while travelling or handling tools {when}; avoid rushing."],
    },
    "family": {
        "pos": ["Family bonds feel warm {when} — good for gatherings and heartfelt talks.",
                "Support from relatives and elders is available {when}; ask if you need it.",
                "Home is harmonious {when}; small acts of care bring big rewards."],
        "mid": ["Home life is steady {when}; share responsibilities and keep routines.",
                "A quiet stretch with family {when} — listen before advising.",
                "No major changes at home {when}; use the time for small repairs or planning."],
        "neg": ["Tension at home is possible {when}; avoid arguments over small things.",
                "Family expectations may feel heavy {when} — communicate calmly and set boundaries.",
                "Misunderstandings with relatives can flare up {when}; give people time."],
    },
}

_MOOD_LINE = {
    "Excellent": "The planets are strongly in your favour {when}.",
    "Good": "{When} looks positive overall, with more support than resistance.",
    "Balanced": "{When} is mixed — some doors open while others need patience.",
    "Challenging": "{When} asks for patience; planetary pressure is above average.",
    "Difficult": "{When} is demanding; move carefully and protect your energy.",
}
_ADVICE = {
    "Excellent": ["Act on what you have been postponing — timing is with you.",
                  "Say yes to opportunities, but stay humble and grateful."],
    "Good": ["Build on the momentum with steady, focused effort.",
             "Share good news with someone who supports you."],
    "Balanced": ["Prioritise one important task and let the rest wait.",
                 "Stay flexible; adapt rather than force outcomes."],
    "Challenging": ["Slow down, double-check details and avoid arguments.",
                    "A short prayer, walk or quiet time will steady your mind."],
    "Difficult": ["Postpone major decisions and conserve energy.",
                  "Lean on trusted people and keep your routine simple."],
}
_WHEN = {"daily": "today", "weekly": "this week", "monthly": "this month", "yearly": "this year"}


# ── Public helpers ────────────────────────────────────────────────────────────

def resolve_sign(value: str) -> int:
    key = value.strip().lower()
    if key in SIGN_ALIASES:
        return SIGN_ALIASES[key]
    raise ValueError(f"Unknown sign '{value}'. Use an English or Sanskrit Moon-sign name.")


def mood_for(score: float) -> str:
    # Thresholds sit at percentiles of the real score distribution (~8% / 20% / 45% / 17% / 10%)
    if score >= 65:
        return "Excellent"
    if score >= 57:
        return "Good"
    if score >= 44:
        return "Balanced"
    if score >= 37:
        return "Challenging"
    return "Difficult"


def _band(score: float) -> str:
    return "pos" if score >= 57 else "neg" if score < 43 else "mid"


def _scale(weighted: float, total: float) -> int:
    return int(max(5, min(98, round(50 + 45 * weighted / total))))


def area_scores(g: dict[str, dict]) -> dict[str, int]:
    out = {}
    for area, weights in _AREA_WEIGHTS.items():
        total = sum(weights.values())
        out[area] = _scale(sum(w * g[p]["value"] for p, w in weights.items()), total)
    total = sum(_OVERALL_WEIGHTS.values())
    out["overall"] = _scale(sum(w * g[p]["value"] for p, w in _OVERALL_WEIGHTS.items()), total)
    return out


# ── Daily core ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _positions_for(day_iso: str, tz: str) -> dict:
    """Positions at local noon, plus Moon sign changes during the local day."""
    day = date.fromisoformat(day_iso)
    midnight = E.local_midnight_jd(day, tz)
    noon = midnight + 0.5
    pos = E.positions(noon)
    start_sign = E.sign_index(E.lon_speed(midnight, "Moon")[0])
    changes = E.ingresses("Moon", midnight, midnight + 1.0)
    return {"pos": pos, "moon_start_sign": start_sign,
            "moon_change": changes[0] if changes else None, "midnight": midnight}


def _pick(bank: list[str], seed: int) -> str:
    return bank[seed % len(bank)]


def _area_texts(scores: dict[str, int], seed: int, when: str) -> dict[str, str]:
    return {a: _pick(_TEXT[a][_band(scores[a])], seed + i).format(when=when)
            for i, a in enumerate(AREAS)}


def _lucky(sign_idx: int, day: date) -> dict:
    lord = SIGN_LORDS[sign_idx]
    day_lord = _DAY_LORD[(day.weekday() + 1) % 7]
    numbers = sorted({_NUMBER[lord], _NUMBER[day_lord]})
    return {
        "numbers": numbers,
        "colour": _COLOUR.get(lord, "White"),
        "supporting_colour": _COLOUR.get(day_lord, "White"),
        "ruling_planet": lord,
    }


def daily(sign_idx: int, day: date, tz: str = "Asia/Kolkata") -> dict:
    ctx = _positions_for(day.isoformat(), tz)
    g = T.gochar(ctx["pos"], sign_idx)
    scores = area_scores(g)
    mood = mood_for(scores["overall"])
    seed = day.toordinal() + sign_idx
    when = _WHEN["daily"]

    moon_house = g["Moon"]["house"]
    moon_info = {
        "sign": ctx["pos"]["Moon"]["sign"],
        "house_from_your_sign": moon_house,
        "nakshatra": ctx["pos"]["Moon"]["nakshatra"],
    }
    if ctx["moon_change"]:
        moon_info["changes_to"] = ctx["moon_change"]["to_sign"]
        moon_info["changes_at"] = E.jd_to_local(ctx["moon_change"]["jd"], tz).strftime("%H:%M")

    ranked = sorted((p for p in g if p != "Moon"), key=lambda p: -abs(g[p]["value"]) * 10 - _OVERALL_WEIGHTS[p])
    influences = [{"planet": "Moon", "house": moon_house, "text": g["Moon"]["text"]}]
    influences += [{"planet": p, "house": g[p]["house"], "text": g[p]["text"]} for p in ranked[:3]]

    return {
        "sign": SIGNS[sign_idx], "sign_index": sign_idx, "ruling_planet": SIGN_LORDS[sign_idx],
        "element": ELEMENTS[sign_idx],
        "period": "daily", "date": day.isoformat(),
        "mood": mood, "scores": scores,
        "summary": f"{_MOOD_LINE[mood].format(when=when, When=when.capitalize())} {g['Moon']['text']}",
        "areas": _area_texts(scores, seed, when),
        "influences": influences,
        "moon": moon_info,
        "lucky": _lucky(sign_idx, day),
        "advice": _pick(_ADVICE[mood], seed),
    }


# ── Multi-day periods ─────────────────────────────────────────────────────────

def _avg(daily_list: list[dict]) -> dict[str, int]:
    return {k: int(round(sum(d["scores"][k] for d in daily_list) / len(daily_list)))
            for k in ("overall", *AREAS)}


def _ingress_notes(
    sign_idx: int, start: date, end: date, tz: str, planets: tuple[str, ...], moon_events: bool = True
) -> list[dict]:
    jd0 = E.local_midnight_jd(start, tz)
    jd1 = E.local_midnight_jd(end + timedelta(days=1), tz)
    notes = []
    for ev in T.upcoming_events(E.from_jd(jd0), int(jd1 - jd0), planets, moon_events):
        if ev["type"] == "ingress":
            house = T.house_from(ev["to_sign_index"], sign_idx)
            good = house in T.FAVOURABLE_HOUSES[ev["planet"]]
            notes.append({
                "date": E.jd_to_local(ev["jd"], tz).date().isoformat(),
                "title": ev["title"], "house": house, "favourable": good,
                "text": f"{ev['planet']} moves into your {T._ORD[house]} house ({T._THEME[house]}): "
                        + ("generally supportive." if good else "go carefully in these matters."),
            })
        elif ev["type"] in ("retrograde_start", "direct_start"):
            notes.append({"date": E.jd_to_local(ev["jd"], tz).date().isoformat(),
                          "title": ev["title"], "text": ev["title"] + "."})
        elif ev["type"] in ("new_moon", "full_moon"):
            moon_sign = SIGNS.index(ev["sign"])
            house = T.house_from(moon_sign, sign_idx)
            notes.append({"date": E.jd_to_local(ev["jd"], tz).date().isoformat(),
                          "title": ev["title"], "house": house,
                          "text": f"{ev['title']} falls in your {T._ORD[house]} house ({T._THEME[house]})."})
    return notes


def _period_summary(period: str, scores: dict[str, int], days: list[dict], seed: int) -> tuple[str, str]:
    when = _WHEN[period]
    mood = mood_for(scores["overall"])
    best = max(days, key=lambda d: d["scores"]["overall"])
    worst = min(days, key=lambda d: d["scores"]["overall"])
    text = _MOOD_LINE[mood].format(when=when, When=when.capitalize())
    if period != "yearly" and len(days) > 1:
        text += (f" Your strongest day is {best['date']} ({best['mood'].lower()}) "
                 f"and the most demanding is {worst['date']}.")
    return mood, text


def weekly(sign_idx: int, start: date, tz: str = "Asia/Kolkata") -> dict:
    days = [daily(sign_idx, start + timedelta(days=i), tz) for i in range(7)]
    scores = _avg(days)
    mood, summary = _period_summary("weekly", scores, days, start.toordinal())
    seed = start.toordinal() + sign_idx
    return {
        "sign": SIGNS[sign_idx], "sign_index": sign_idx, "ruling_planet": SIGN_LORDS[sign_idx],
        "element": ELEMENTS[sign_idx], "period": "weekly",
        "range": {"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat()},
        "mood": mood, "scores": scores, "summary": summary,
        "areas": _area_texts(scores, seed, _WHEN["weekly"]),
        "daily": [{"date": d["date"], "mood": d["mood"], "overall": d["scores"]["overall"],
                   "moon_sign": d["moon"]["sign"]} for d in days],
        "key_dates": _ingress_notes(sign_idx, start, start + timedelta(days=6), tz,
                                    ("Sun", "Mars", "Mercury", "Venus", "Jupiter", "Saturn")),
        "lucky": _lucky(sign_idx, start),
        "advice": _pick(_ADVICE[mood], seed),
    }


def monthly(sign_idx: int, year: int, month: int, tz: str = "Asia/Kolkata") -> dict:
    last = calendar.monthrange(year, month)[1]
    start, end = date(year, month, 1), date(year, month, last)
    days = [daily(sign_idx, start + timedelta(days=i), tz) for i in range(last)]
    scores = _avg(days)
    mood, summary = _period_summary("monthly", scores, days, year * 12 + month)
    seed = year * 12 + month + sign_idx
    weeks = []
    for w in range(0, last, 7):
        chunk = days[w:w + 7]
        weeks.append({"from": chunk[0]["date"], "to": chunk[-1]["date"],
                      "overall": int(round(sum(d["scores"]["overall"] for d in chunk) / len(chunk))),
                      "mood": mood_for(sum(d["scores"]["overall"] for d in chunk) / len(chunk))})
    return {
        "sign": SIGNS[sign_idx], "sign_index": sign_idx, "ruling_planet": SIGN_LORDS[sign_idx],
        "element": ELEMENTS[sign_idx], "period": "monthly",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "mood": mood, "scores": scores, "summary": summary,
        "areas": _area_texts(scores, seed, _WHEN["monthly"]),
        "weeks": weeks,
        "key_dates": _ingress_notes(sign_idx, start, end, tz,
                                    ("Sun", "Mars", "Mercury", "Venus", "Jupiter", "Saturn", "Rahu")),
        "lucky": _lucky(sign_idx, start),
        "advice": _pick(_ADVICE[mood], seed),
    }


def _slow_influences(sign_idx: int, year: int, tz: str) -> list[dict]:
    """Where Saturn, Jupiter and the nodes stand relative to the sign in mid-year."""
    pos = _positions_for(date(year, 7, 1).isoformat(), tz)["pos"]
    g = T.gochar(pos, sign_idx)
    return [{"planet": p, "house": g[p]["house"], "favourable": g[p]["favourable"], "text": g[p]["text"]}
            for p in ("Jupiter", "Saturn", "Rahu", "Ketu")]


def yearly(sign_idx: int, year: int, tz: str = "Asia/Kolkata") -> dict:
    months = []
    all_days: list[dict] = []
    for m in range(1, 13):
        last = calendar.monthrange(year, m)[1]
        sample = [daily(sign_idx, date(year, m, d), tz) for d in range(1, last + 1, 3)]
        all_days.extend(sample)
        sc = _avg(sample)
        months.append({"month": f"{calendar.month_name[m]} {year}", "month_number": m,
                       "scores": sc, "mood": mood_for(sc["overall"])})
    scores = _avg(all_days)
    seed = year + sign_idx
    mood = mood_for(scores["overall"])
    ss = T.sade_sati_timeline(sign_idx, datetime(year, 7, 1, tzinfo=timezone.utc), span_years=3)
    ss_year = [p for p in ss["periods"] if p["start"] <= f"{year}-12-31" and p["end"] >= f"{year}-01-01"]
    best = max(months, key=lambda m: m["scores"]["overall"])
    worst = min(months, key=lambda m: m["scores"]["overall"])
    summary = (f"{_MOOD_LINE[mood].format(when='this year', When='This year')} "
               f"Your best month is {best['month']} and the most demanding is {worst['month']}.")
    return {
        "sign": SIGNS[sign_idx], "sign_index": sign_idx, "ruling_planet": SIGN_LORDS[sign_idx],
        "element": ELEMENTS[sign_idx], "period": "yearly", "year": year,
        "mood": mood, "scores": scores, "summary": summary,
        "areas": _area_texts(scores, seed, _WHEN["yearly"]),
        "months": months,
        "slow_planet_transits": _ingress_notes(sign_idx, date(year, 1, 1), date(year, 12, 31), tz,
                                               ("Saturn", "Jupiter", "Rahu"), moon_events=False),
        "key_influences": _slow_influences(sign_idx, year, tz),
        "sade_sati_or_dhaiya": ss_year,
        "lucky": _lucky(sign_idx, date(year, 1, 1)),
        "advice": _pick(_ADVICE[mood], seed),
    }


def forecast(sign: str, period: str, on: date | None, tz: str = "Asia/Kolkata", today: date | None = None) -> dict:
    sign_idx = resolve_sign(sign)
    today = today or datetime.now(E.tzinfo(tz)).date()
    on = on or today
    if period == "today":
        return daily(sign_idx, today, tz)
    if period == "tomorrow":
        return daily(sign_idx, today + timedelta(days=1), tz)
    if period == "daily":
        return daily(sign_idx, on, tz)
    if period == "weekly":
        return weekly(sign_idx, on, tz)
    if period == "monthly":
        return monthly(sign_idx, on.year, on.month, tz)
    if period == "yearly":
        return yearly(sign_idx, on.year, tz)
    raise ValueError("period must be one of: today, tomorrow, daily, weekly, monthly, yearly")
