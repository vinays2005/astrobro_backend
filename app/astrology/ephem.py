"""Shared Swiss Ephemeris helpers for date-based (non-natal) calculations. Lahiri sidereal.

Every public function re-asserts the Lahiri sidereal mode under a lock, because
swe.set_sid_mode() is process-global and other engines may have changed it.
"""
from __future__ import annotations

import threading
import zoneinfo
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import swisseph as swe

from app.astrology.constants import NAKSHATRAS, SIGNS

_LOCK = threading.RLock()
_FLAGS = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
_BODIES = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.TRUE_NODE,
}
# Search step (days) that cannot skip a sign change for each body
_STEP = {
    "Moon": 0.25, "Sun": 1.0, "Mercury": 1.0, "Venus": 1.0, "Mars": 1.0,
    "Jupiter": 5.0, "Saturn": 5.0, "Rahu": 5.0, "Ketu": 5.0,
}
NAK_SPAN = 360.0 / 27.0


# ── Time helpers ──────────────────────────────────────────────────────────────

def to_jd(dt: datetime) -> float:
    """Julian day (UT) for an aware datetime, or a naive one taken as UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0)


def from_jd(jd: float) -> datetime:
    y, mo, d, hf = swe.revjul(jd)
    base = datetime(y, mo, d, tzinfo=timezone.utc)
    return base + timedelta(hours=hf)


def tzinfo(name: str):
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:
        return zoneinfo.ZoneInfo("Asia/Kolkata")


def local_midnight_jd(day, tz: str) -> float:
    """JD (UT) of local midnight at the start of a calendar date."""
    return to_jd(datetime(day.year, day.month, day.day, tzinfo=tzinfo(tz)))


def jd_to_local(jd: float, tz: str) -> datetime:
    return from_jd(jd).astimezone(tzinfo(tz))


# ── Positions ─────────────────────────────────────────────────────────────────

def _calc(jd: float, name: str) -> tuple[float, float]:
    """(sidereal longitude, daily speed) — caller must hold _LOCK."""
    if name == "Ketu":
        lon, speed = _calc(jd, "Rahu")
        return (lon + 180.0) % 360.0, speed
    pos, _ = swe.calc_ut(jd, _BODIES[name], _FLAGS)
    return pos[0] % 360.0, pos[3]


def lon_speed(jd: float, name: str) -> tuple[float, float]:
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        return _calc(jd, name)


def sign_index(lon: float) -> int:
    return int(lon / 30.0) % 12


def nakshatra_index(lon: float) -> int:
    return int(lon / NAK_SPAN) % 27


def pada(lon: float) -> int:
    return int((lon % NAK_SPAN) / (NAK_SPAN / 4)) + 1


def positions(jd: float) -> dict[str, dict]:
    """Sidereal positions of all nine grahas at a Julian day."""
    out: dict[str, dict] = {}
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        for name in PLANETS:
            lon, speed = _calc(jd, name)
            si = sign_index(lon)
            out[name] = {
                "longitude": round(lon, 4),
                "speed": round(speed, 4),
                "sign_index": si,
                "sign": SIGNS[si],
                "degree": round(lon % 30.0, 2),
                "nakshatra": NAKSHATRAS[nakshatra_index(lon)],
                "nakshatra_index": nakshatra_index(lon),
                "pada": pada(lon),
                # Rahu/Ketu are always retrograde on average; the Sun and Moon never are
                "retrograde": speed < 0 and name not in ("Sun", "Moon", "Rahu", "Ketu"),
            }
    return out


# ── Event finders ─────────────────────────────────────────────────────────────

def ingresses(name: str, jd_start: float, jd_end: float) -> list[dict]:
    """Sign changes of one graha between two Julian days (retrograde re-entries included)."""
    step = _STEP.get(name, 1.0)
    events: list[dict] = []
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        t = jd_start
        prev = sign_index(_calc(t, name)[0])
        while t < jd_end:
            t2 = min(t + step, jd_end)
            cur = sign_index(_calc(t2, name)[0])
            if cur != prev:
                lo, hi = t, t2
                for _ in range(40):
                    mid = (lo + hi) / 2.0
                    if sign_index(_calc(mid, name)[0]) == prev:
                        lo = mid
                    else:
                        hi = mid
                events.append({
                    "jd": hi, "planet": name,
                    "from_sign": SIGNS[prev], "to_sign": SIGNS[cur],
                    "to_sign_index": cur,
                    "retrograde": _calc(hi, name)[1] < 0 and name not in ("Sun", "Moon", "Rahu", "Ketu"),
                })
                prev = cur
            t = t2
    return events


def stations(name: str, jd_start: float, jd_end: float) -> list[dict]:
    """Retrograde / direct turning points of a graha (speed changes sign)."""
    if name in ("Sun", "Moon", "Rahu", "Ketu"):
        return []
    step = _STEP.get(name, 1.0)
    events: list[dict] = []
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        t = jd_start
        prev = _calc(t, name)[1] < 0
        while t < jd_end:
            t2 = min(t + step, jd_end)
            cur = _calc(t2, name)[1] < 0
            if cur != prev:
                lo, hi = t, t2
                for _ in range(40):
                    mid = (lo + hi) / 2.0
                    if (_calc(mid, name)[1] < 0) == prev:
                        lo = mid
                    else:
                        hi = mid
                lon = _calc(hi, name)[0]
                events.append({
                    "jd": hi, "planet": name,
                    "type": "retrograde_start" if cur else "direct_start",
                    "sign": SIGNS[sign_index(lon)], "degree": round(lon % 30.0, 2),
                })
                prev = cur
            t = t2
    return events


def elongation(jd: float) -> float:
    """Moon minus Sun, 0-360 degrees."""
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        return (_calc(jd, "Moon")[0] - _calc(jd, "Sun")[0]) % 360.0


def tithi_number(jd: float) -> int:
    """1-30 (1-15 Shukla, 16-30 Krishna)."""
    return int(elongation(jd) / 12.0) + 1


def lunations(jd_start: float, jd_end: float, target: float = 0.0) -> list[float]:
    """JDs when the Moon-Sun elongation passes `target` (0 = new moon, 180 = full moon)."""
    found: list[float] = []
    with _LOCK:
        swe.set_sid_mode(swe.SIDM_LAHIRI)

        def delta(jd: float) -> float:
            e = (_calc(jd, "Moon")[0] - _calc(jd, "Sun")[0]) % 360.0
            return ((e - target + 180.0) % 360.0) - 180.0  # -180..180, 0 at the target

        t = jd_start
        prev = delta(t)
        while t < jd_end:
            t2 = min(t + 1.0, jd_end)
            cur = delta(t2)
            if prev < 0 <= cur and (cur - prev) < 90:
                lo, hi = t, t2
                for _ in range(40):
                    mid = (lo + hi) / 2.0
                    if delta(mid) < 0:
                        lo = mid
                    else:
                        hi = mid
                found.append(hi)
            prev, t = cur, t2
    return found


@lru_cache(maxsize=64)
def sun_sign_at(jd_rounded: float) -> int:
    return sign_index(lon_speed(jd_rounded, "Sun")[0])


def moon_phase_name(elong: float) -> str:
    phases = [
        (45, "Waxing Crescent"), (90, "First Quarter"), (135, "Waxing Gibbous"),
        (180, "Full Moon"), (225, "Waning Gibbous"), (270, "Last Quarter"),
        (315, "Waning Crescent"), (360, "New Moon"),
    ]
    if elong < 6 or elong >= 354:
        return "New Moon"
    return next(name for limit, name in phases if elong < limit)


# ── Rise / set ────────────────────────────────────────────────────────────────

def _rise_set(jd_from: float, body: int, flag: int, lat: float, lon: float) -> float | None:
    """First rise/set of a body after jd_from, or None for circumpolar cases."""
    try:
        res, tret = swe.rise_trans(jd_from, body, flag, (lon, lat, 0.0), 0.0, 0.0, swe.FLG_SWIEPH)
    except Exception:
        return None
    return tret[0] if res == 0 else None


def sun_rise_set(jd_from: float, lat: float, lon: float) -> tuple[float | None, float | None]:
    """(sunrise_jd, sunset_jd): first upper-limb rise and set after jd_from."""
    with _LOCK:
        return (_rise_set(jd_from, swe.SUN, swe.CALC_RISE, lat, lon),
                _rise_set(jd_from, swe.SUN, swe.CALC_SET, lat, lon))


def moon_rise_set(jd_from: float, lat: float, lon: float) -> tuple[float | None, float | None]:
    with _LOCK:
        return (_rise_set(jd_from, swe.MOON, swe.CALC_RISE, lat, lon),
                _rise_set(jd_from, swe.MOON, swe.CALC_SET, lat, lon))
