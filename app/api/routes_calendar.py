"""Hindu calendar API: festivals, vratas, sankrantis and a day summary."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.common import utc_now, valid_tz
from app.astrology import calendar_hindu as CH
from app.astrology import ephem as E
from app.astrology.panchang import PanchangEngine
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/calendar", tags=["calendar"], dependencies=[Depends(require_api_key)])
_panchang = PanchangEngine()

_NOTE = ("Dates use the tithi at the traditional observance time and can differ by a day from regional panchangs. "
         "Confirm with your local temple or panchang for religious observance.")


def _events(year: int, lat: float, lon: float, tz: str) -> list[dict]:
    return CH.events_for_year(year, lat, lon, tz)


@router.get("/festivals")
async def festivals(
    year: int = Query(..., ge=1950, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    kind: str | None = Query(None, pattern="^(festival|vrata|sankranti)$"),
    lat: float = Query(CH.DEFAULT_LAT, ge=-90, le=90),
    lon: float = Query(CH.DEFAULT_LON, ge=-180, le=180),
    tz: str = Query(CH.DEFAULT_TZ),
) -> dict:
    valid_tz(tz)
    events = _events(year, lat, lon, tz)
    if month:
        events = [e for e in events if e["date"][5:7] == f"{month:02d}"]
    if kind:
        events = [e for e in events if e["type"] == kind]
    return {"year": year, "month": month, "count": len(events), "events": events, "note": _NOTE}


@router.get("/upcoming")
async def upcoming(
    days: int = Query(30, ge=1, le=120),
    kind: str | None = Query(None, pattern="^(festival|vrata|sankranti)$"),
    lat: float = Query(CH.DEFAULT_LAT, ge=-90, le=90),
    lon: float = Query(CH.DEFAULT_LON, ge=-180, le=180),
    tz: str = Query(CH.DEFAULT_TZ),
) -> dict:
    valid_tz(tz)
    today = utc_now().astimezone(E.tzinfo(tz)).date()
    end = today + timedelta(days=days)
    events = []
    for y in sorted({today.year, end.year}):
        events += _events(y, lat, lon, tz)
    events = [e for e in events if today <= date.fromisoformat(e["date"]) <= end and (not kind or e["type"] == kind)]
    return {"from": today.isoformat(), "to": end.isoformat(), "count": len(events), "events": events, "note": _NOTE}


@router.get("/today")
async def today(
    on: date | None = Query(None, alias="date"),
    lat: float = Query(CH.DEFAULT_LAT, ge=-90, le=90),
    lon: float = Query(CH.DEFAULT_LON, ge=-180, le=180),
    tz: str = Query(CH.DEFAULT_TZ),
) -> dict:
    """The day at a glance: tithi, nakshatra, month, Hindu year, sunrise/sunset and any festival."""
    valid_tz(tz)
    day = on or utc_now().astimezone(E.tzinfo(tz)).date()
    p = _panchang.calculate(day, lat, lon, tz)
    return {
        "date": day.isoformat(), "weekday": p.vara,
        "tithi": f"{p.tithi.paksha} {p.tithi.name}", "tithi_ends": p.tithi.end_time,
        "nakshatra": p.nakshatra.name, "nakshatra_ends": p.nakshatra.end_time,
        "yoga": p.yoga.name, "karana": p.karana.name,
        "month": {"amanta": p.masa, "purnimanta": p.masa_purnimanta, "adhika": p.adhika_masa},
        "vikram_samvat": p.vikram_samvat, "shaka_samvat": p.shaka_samvat, "ritu": p.ritu, "moon_phase": p.moon_phase,
        "sunrise": p.sun_moon.sunrise, "sunset": p.sun_moon.sunset,
        "moonrise": p.sun_moon.moonrise, "moonset": p.sun_moon.moonset,
        "rahu_kaal": p.rahu_kaal, "abhijit_muhurat": p.abhijit_muhurat,
        "events_today": [e for e in _events(day.year, lat, lon, tz) if e["date"] == day.isoformat()],
        "note": _NOTE,
    }
