"""Shubh Muhurat finder: ranks days and time windows for common events from Panchang rules.

Traditional guidance only. Rules are condensed from common Muhurta practice; regional traditions and
a personal horoscope can refine or override them, so confirm important dates with a qualified astrologer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache

from app.astrology import calendar_hindu as CH
from app.astrology import ephem as E
from app.astrology import panchang as P
from app.astrology.constants import NAKSHATRAS

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_NAK = lambda *names: frozenset(names)  # noqa: E731

_MARRIAGE_STARS = _NAK("Rohini", "Mrigashira", "Magha", "Uttara Phalguni", "Hasta", "Swati", "Anuradha",
                       "Mula", "Uttara Ashadha", "Uttara Bhadrapada", "Revati")
_FIXED_STARS = _NAK("Rohini", "Mrigashira", "Uttara Phalguni", "Uttara Ashadha", "Uttara Bhadrapada", "Anuradha",
                    "Revati", "Hasta", "Chitra", "Swati", "Dhanishta", "Shatabhisha", "Punarvasu", "Pushya")
_PURCHASE_STARS = _NAK("Ashwini", "Rohini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Chitra", "Swati",
                       "Anuradha", "Shravana", "Dhanishta", "Shatabhisha", "Revati")
_BUSINESS_STARS = _NAK("Ashwini", "Rohini", "Mrigashira", "Punarvasu", "Pushya", "Uttara Phalguni", "Hasta",
                       "Chitra", "Anuradha", "Uttara Ashadha", "Shravana", "Dhanishta", "Revati")
_CHILD_STARS = _NAK("Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Chitra", "Swati", "Shravana",
                    "Dhanishta", "Shatabhisha")
_NAMING_STARS = _NAK("Ashwini", "Rohini", "Mrigashira", "Punarvasu", "Pushya", "Uttara Phalguni", "Hasta",
                     "Chitra", "Swati", "Anuradha", "Shravana", "Dhanishta", "Shatabhisha", "Uttara Ashadha",
                     "Uttara Bhadrapada", "Revati")
_TRAVEL_STARS = _NAK("Ashwini", "Mrigashira", "Punarvasu", "Pushya", "Hasta", "Anuradha", "Shravana",
                     "Dhanishta", "Revati")
_GOOD_DAYS = frozenset({0, 2, 3, 4})  # Monday, Wednesday, Thursday, Friday
_TITHIS = frozenset({2, 3, 5, 7, 10, 11, 12, 13})
_ALL_DAYS = frozenset(range(7))


@dataclass(frozen=True)
class EventRule:
    key: str
    label: str
    description: str
    weekdays: frozenset[int]
    nakshatras: frozenset[str] | None
    tithis: frozenset[int] | None       # paksha-day numbers 1..15 (15 = Purnima); None = any except Rikta/Amavasya
    banned: frozenset[str]
    best_nakshatras: frozenset[str] = frozenset()
    favoured_weekdays: frozenset[int] = frozenset()
    allow_char: bool = False
    prefers_shukla: bool = True
    pushya_yoga: bool = False   # Guru/Ravi Pushya overrides the weekday rule
    abujh: bool = False         # self-auspicious days count without further matching


RULES: dict[str, EventRule] = {r.key: r for r in [
    EventRule("marriage", "Marriage (Vivah)", "Wedding ceremony", _GOOD_DAYS, _MARRIAGE_STARS, _TITHIS,
              frozenset({"chaturmas", "kharmas", "adhika", "pitru_paksha", "asta"}),
              best_nakshatras=_NAK("Rohini", "Uttara Phalguni", "Hasta", "Swati", "Anuradha", "Revati"),
              favoured_weekdays=frozenset({3, 4})),
    EventRule("engagement", "Engagement (Sagai)", "Engagement or betrothal", _GOOD_DAYS, _MARRIAGE_STARS,
              _TITHIS | {15}, frozenset({"pitru_paksha", "adhika"}), favoured_weekdays=frozenset({3, 4})),
    EventRule("griha_pravesh", "Griha Pravesh (Housewarming)", "Entering a new home", _GOOD_DAYS, _FIXED_STARS,
              _TITHIS | {15}, frozenset({"chaturmas", "kharmas", "adhika", "pitru_paksha", "asta"}),
              best_nakshatras=_NAK("Rohini", "Uttara Phalguni", "Uttara Ashadha", "Uttara Bhadrapada", "Revati"),
              favoured_weekdays=frozenset({3, 4, 0}), abujh=True),
    EventRule("vehicle_purchase", "Vehicle purchase", "Buying a vehicle", _GOOD_DAYS, _PURCHASE_STARS,
              _TITHIS | {1, 15}, frozenset({"pitru_paksha", "adhika"}),
              best_nakshatras=_NAK("Pushya", "Ashwini", "Hasta", "Revati", "Shravana"),
              favoured_weekdays=frozenset({3, 4, 0}), pushya_yoga=True, abujh=True),
    EventRule("property_purchase", "Property purchase", "Buying land or a home", _GOOD_DAYS, _FIXED_STARS,
              _TITHIS | {15}, frozenset({"pitru_paksha", "adhika"}),
              best_nakshatras=_NAK("Rohini", "Uttara Phalguni", "Pushya", "Uttara Ashadha", "Uttara Bhadrapada"),
              favoured_weekdays=frozenset({3, 4}), pushya_yoga=True, abujh=True),
    EventRule("business_launch", "Business launch", "Starting a business or opening an office", _GOOD_DAYS,
              _BUSINESS_STARS, _TITHIS | {1, 15}, frozenset({"pitru_paksha", "adhika"}),
              best_nakshatras=_NAK("Pushya", "Hasta", "Revati", "Ashwini", "Rohini"),
              favoured_weekdays=frozenset({3, 4, 2}), pushya_yoga=True, abujh=True),
    EventRule("naming_ceremony", "Naming ceremony (Namkaran)", "Naming a child", _GOOD_DAYS, _NAMING_STARS,
              _TITHIS, frozenset({"adhika"}), favoured_weekdays=frozenset({3, 4, 0})),
    EventRule("mundan", "Mundan (first haircut)", "Tonsure ceremony", _GOOD_DAYS, _CHILD_STARS, _TITHIS,
              frozenset({"chaturmas", "kharmas", "adhika", "asta"}), favoured_weekdays=frozenset({3, 4, 2})),
    EventRule("upanayana", "Upanayana (sacred thread)", "Thread ceremony", _GOOD_DAYS, _CHILD_STARS | {"Rohini"},
              _TITHIS, frozenset({"chaturmas", "kharmas", "adhika", "asta"}), favoured_weekdays=frozenset({3, 4, 2})),
    EventRule("puja", "Puja / religious ceremony", "General worship, havan or katha", _ALL_DAYS, None, None,
              frozenset({"adhika"}), favoured_weekdays=frozenset({3, 0, 4}), abujh=True),
    EventRule("travel", "Travel (Yatra)", "Starting a journey", _ALL_DAYS, _TRAVEL_STARS, None, frozenset(),
              allow_char=True, prefers_shukla=False),
]}

_BANNED_TEXT = {
    "chaturmas": "Chaturmas (Devshayani to Dev Uthani Ekadashi) is avoided for this event",
    "kharmas": "Kharmas (Sun in Sagittarius or Pisces) is avoided for this event",
    "adhika": "Adhika (extra) lunar month is avoided for this event",
    "pitru_paksha": "Pitru Paksha is avoided for new beginnings",
    "asta": "Venus or Jupiter is combust (asta), which is avoided for this event",
}
_YOGA_SPAN = 360.0 / 27.0


# ── Period flags ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=4096)
def _period_flags(jd_key: float) -> frozenset[str]:
    """Calendar-level exclusions at an instant (rounded to the day for caching)."""
    jd = jd_key
    flags: set[str] = set()
    info = CH.masa_info(jd)
    tithi = E.tithi_number(jd)
    masa = info.get("amanta", "")
    if info.get("adhika"):
        flags.add("adhika")
    if (masa == "Ashadha" and tithi >= 11) or masa in ("Shravana", "Bhadrapada", "Ashwin") or \
            (masa == "Kartik" and tithi < 11):
        flags.add("chaturmas")
    if masa == "Bhadrapada" and tithi >= 16:
        flags.add("pitru_paksha")
    pos = E.positions(jd)
    if pos["Sun"]["sign_index"] in (8, 11):
        flags.add("kharmas")
    sun = pos["Sun"]["longitude"]
    for planet, orb, retro_orb in (("Venus", 10.0, 8.0), ("Jupiter", 11.0, 11.0)):
        diff = abs(pos[planet]["longitude"] - sun) % 360
        diff = 360 - diff if diff > 180 else diff
        if diff <= (retro_orb if pos[planet]["retrograde"] else orb):
            flags.add("asta")
    return frozenset(flags)


# ── Instant evaluation ────────────────────────────────────────────────────────

def _instant(jd: float) -> dict:
    pos = E.positions(jd)
    elong = E.elongation(jd)
    tithi = int(elong / 12.0) + 1
    k = int(elong / 6.0)
    karana = P._FIXED_KARANAS.get(k) or P._KARANA_NAMES[(k - 1) % 7]
    yoga = P._YOGA_NAMES[int(((pos["Sun"]["longitude"] + pos["Moon"]["longitude"]) % 360.0) / _YOGA_SPAN) % 27]
    paksha, tname = CH.tithi_label(tithi)
    return {
        "tithi_number": tithi, "paksha_day": tithi if tithi <= 15 else tithi - 15,
        "tithi": f"{paksha} {tname}", "paksha": paksha, "amavasya": tithi == 30,
        "nakshatra": pos["Moon"]["nakshatra"], "yoga": yoga, "karana": karana,
        "vishti": karana == "Vishti",
    }


def _check(rule: EventRule, jd: float, weekday: int) -> list[str]:
    """Reasons an instant fails the event's rules (empty list = suitable)."""
    ins = _instant(jd)
    why: list[str] = []
    pushya_ok = rule.pushya_yoga and ins["nakshatra"] == "Pushya" and weekday in (3, 6)
    if weekday not in rule.weekdays and not pushya_ok:
        why.append(f"{_WEEKDAYS[weekday]} is not recommended")
    if ins["amavasya"]:
        why.append("Amavasya is avoided")
    elif ins["paksha_day"] in (4, 9, 14):
        why.append(f"{ins['tithi']} is a Rikta tithi")
    elif rule.tithis is not None and ins["paksha_day"] not in rule.tithis:
        why.append(f"{ins['tithi']} is not favoured")
    if rule.nakshatras is not None and ins["nakshatra"] not in rule.nakshatras:
        why.append(f"{ins['nakshatra']} nakshatra is not suitable")
    if ins["yoga"] in P._INAUSPICIOUS_YOGAS:
        why.append(f"{ins['yoga']} yoga is inauspicious")
    if ins["vishti"]:
        why.append("Bhadra (Vishti karana) is running")
    return why


# ── Self-auspicious (Abujh) days ──────────────────────────────────────────────

_ABUJH_KEYS = {"ugadi": "Gudi Padwa / Ugadi", "akshaya_tritiya": "Akshaya Tritiya",
               "dussehra": "Vijayadashami (Dussehra)", "govardhan_puja": "Bali Pratipada / Govardhan Puja"}


@lru_cache(maxsize=64)
def _abujh_dates(year: int, lat: float, lon: float, tz: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in CH.events_for_year(year, lat, lon, tz):
        if e["key"] in _ABUJH_KEYS:
            out[e["date"]] = _ABUJH_KEYS[e["key"]]
    return out


# ── Day evaluation ────────────────────────────────────────────────────────────

def _subtract(win: tuple[float, float], blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    parts = [win]
    for b0, b1 in blocks:
        nxt = []
        for s, e in parts:
            if b1 <= s or b0 >= e:
                nxt.append((s, e))
                continue
            if s < b0:
                nxt.append((s, b0))
            if e > b1:
                nxt.append((b1, e))
        parts = nxt
    return [(s, e) for s, e in parts if (e - s) * 1440.0 >= 25.0]


def _fmt(jd: float, tz: str) -> str:
    return E.jd_to_local(jd, tz).strftime("%H:%M")


def evaluate_day(rule: EventRule, d: date, lat: float, lon: float, tz: str) -> dict:
    t = CH.day_times(d, lat, lon, tz)
    sr, ss = t["sunrise"], t["sunset"]
    vara = (d.weekday() + 1) % 7  # Sunday = 0
    span = ss - sr
    eighth = span / 8.0
    slot = lambda n: (sr + (n - 1) * eighth, sr + n * eighth)  # noqa: E731
    blocks = [slot(P._RAHU_KAAL_EIGHTH[vara]), slot(P._YAMAGANDAM_EIGHTH[vara]), slot(P._GULIKA_EIGHTH[vara])]
    mid = (sr + ss) / 2.0
    abhijit = (mid - 24.0 / 1440.0, mid + 24.0 / 1440.0)

    reasons: list[str] = []
    flags = _period_flags(round(sr, 1)) & rule.banned
    reasons += [_BANNED_TEXT[f] for f in sorted(flags)]

    allowed = {"Amrit", "Shubh", "Labh"} | ({"Char"} if rule.allow_char else set())
    names = P.choghadiya_names(vara)
    candidates = [(f"{name} Choghadiya", sr + i * eighth, sr + (i + 1) * eighth)
                  for i, name in enumerate(names) if name in allowed]
    candidates.append(("Abhijit Muhurat", *abhijit))

    windows: list[dict] = []
    if not flags:
        for label, w0, w1 in candidates:
            for s, e in _subtract((w0, w1), blocks):
                m = (s + e) / 2.0
                if not _check(rule, m, d.weekday()):
                    ins = _instant(m)
                    windows.append({"start": _fmt(s, tz), "end": _fmt(e, tz), "type": label,
                                    "tithi": ins["tithi"], "nakshatra": ins["nakshatra"],
                                    "yoga": ins["yoga"], "karana": ins["karana"], "_m": m, "_s": s, "_e": e})
    abujh_name = _abujh_dates(d.year, round(lat, 1), round(lon, 1), tz).get(d.isoformat()) if rule.abujh else None
    if abujh_name and not flags and not windows:
        # Self-auspicious day: usable without matching tithi, nakshatra or weekday, but still outside Rahu Kaal
        for label, w0, w1 in candidates:
            for s0, e0 in _subtract((w0, w1), blocks):
                ins = _instant((s0 + e0) / 2.0)
                if not ins["vishti"]:  # Abujh days skip tithi/nakshatra/yoga matching; Bhadra is still avoided
                    windows.append({"start": _fmt(s0, tz), "end": _fmt(e0, tz), "type": label, "tithi": ins["tithi"],
                                    "nakshatra": ins["nakshatra"], "yoga": ins["yoga"], "karana": ins["karana"],
                                    "_m": 0.0, "_s": s0, "_e": e0})
    if not windows:
        why = _check(rule, mid, d.weekday())
        return {"date": d.isoformat(), "weekday": _WEEKDAYS[d.weekday()], "suitable": False,
                "reasons": reasons + why or ["No clear window free of Rahu Kaal and other inauspicious periods"]}

    best_star = any(w["nakshatra"] in rule.best_nakshatras for w in windows)
    types = {w["type"] for w in windows}
    score = 55
    score += 12 if "Abhijit Muhurat" in types else 0
    score += 9 if "Amrit Choghadiya" in types else 4 if "Shubh Choghadiya" in types else 2
    score += 10 if best_star else 0
    score += 6 if d.weekday() in rule.favoured_weekdays else 0
    first = windows[0]
    score += 4 if rule.prefers_shukla and first["tithi"].startswith("Shukla") else 0
    score = min(score, 99)
    highlights = []
    if abujh_name:
        highlights.append(f"{abujh_name} is a self-auspicious (Abujh) day")
        score = max(score, 88)
    if any(w["nakshatra"] == "Pushya" for w in windows) and d.weekday() in (3, 6) and rule.pushya_yoga:
        highlights.append("Guru Pushya Yoga" if d.weekday() == 3 else "Ravi Pushya Yoga")
        score = max(score, 90)
    if "Abhijit Muhurat" in types:
        highlights.append("Abhijit Muhurat is free of inauspicious factors")
    if best_star:
        highlights.append("A particularly favourable nakshatra is active")
    if d.weekday() in rule.favoured_weekdays:
        highlights.append(f"{_WEEKDAYS[d.weekday()]} is especially favoured")
    for w in windows:
        w.pop("_m"), w.pop("_s"), w.pop("_e")
    return {
        "date": d.isoformat(), "weekday": _WEEKDAYS[d.weekday()], "suitable": True, "score": score,
        "rating": "excellent" if score >= 85 else "good" if score >= 72 else "fair",
        "tithi": first["tithi"], "nakshatra": first["nakshatra"], "yoga": first["yoga"],
        "windows": windows[:6], "highlights": highlights,
        "avoid": {name: f"{_fmt(b[0], tz)}-{_fmt(b[1], tz)}"
                  for name, b in zip(("rahu_kaal", "yamagandam", "gulika"), blocks)},
    }


def find(event: str, start: date, end: date, lat: float, lon: float, tz: str,
         include_excluded: bool = False, limit: int = 40, relaxed: bool = False) -> dict:
    if event not in RULES:
        raise ValueError(f"Unknown event '{event}'. Choose from: {', '.join(RULES)}")
    if end < start:
        raise ValueError("end date must not be before start date")
    if (end - start).days > 150:
        raise ValueError("Date range is limited to 150 days")
    rule = RULES[event]
    if relaxed:  # also allow Saturday/Sunday and Shukla Pratipada/Purnima; Tuesday stays excluded
        rule = replace(rule, weekdays=frozenset(range(7)) - {1},
                       tithis=None if rule.tithis is None else rule.tithis | {1, 15})
    days, excluded = [], []
    d = start
    while d <= end:
        r = evaluate_day(rule, d, lat, lon, tz)
        (days if r["suitable"] else excluded).append(r)
        d += timedelta(days=1)
    ranked = sorted(days, key=lambda r: (-r["score"], r["date"]))[:limit]
    out = {
        "event": event, "label": rule.label, "description": rule.description,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "location": {"latitude": lat, "longitude": lon, "timezone": tz},
        "mode": "relaxed" if relaxed else "strict", "suitable_days": len(days),
        "best_days": ranked,
        "all_suitable_dates": sorted(r["date"] for r in days),
        "summary": (f"{len(days)} suitable day(s) found for {rule.label.lower()} between {start} and {end}."
                    if days else f"No suitable day found for {rule.label.lower()} in this range; try a wider range."),
        "notes": [
            "Windows exclude Rahu Kaal, Yamagandam and Gulika, and avoid Bhadra and inauspicious yogas.",
            "For weddings and housewarmings the couple's or family's horoscope should be matched by an astrologer.",
        ],
        "disclaimer": "Muhurat rules vary by region and tradition. This is guidance, not a substitute for a qualified astrologer.",
    }
    if include_excluded:
        out["excluded_days"] = excluded
    return out


def event_types() -> list[dict]:
    return [{"key": r.key, "label": r.label, "description": r.description,
             "recommended_weekdays": sorted(_WEEKDAYS[i] for i in r.weekdays) if r.weekdays != _ALL_DAYS else "any",
             "excluded_periods": sorted(r.banned)} for r in RULES.values()]


def nakshatra_names() -> list[str]:
    return list(NAKSHATRAS)
