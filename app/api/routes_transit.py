"""Transit API: current planetary positions, Gochar from the natal chart, Sade Sati and upcoming events."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.common import chart_from_birth, utc_now, valid_tz
from app.astrology import ephem as E
from app.astrology import horoscope as H
from app.astrology import transits as T
from app.models.features import BirthOnlyRequest, NatalTransitRequest
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/transit", tags=["transit"], dependencies=[Depends(require_api_key)])

_PLANETS = {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}


@router.get("/current")
async def current_transits(tz: str = Query("Asia/Kolkata")) -> dict:
    """Where every graha is right now (sidereal, Lahiri)."""
    valid_tz(tz)
    now = utc_now()
    data = T.current_transits(now)
    elong = E.elongation(E.to_jd(now))
    data["moon_phase"] = E.moon_phase_name(elong)
    data["local_time"] = now.astimezone(E.tzinfo(tz)).isoformat()
    return data


@router.post("/natal")
async def natal_transits(req: NatalTransitRequest) -> dict:
    """Gochar: today's transits measured from your natal Moon (and Lagna), with Vedha."""
    valid_tz(req.tz)
    chart = chart_from_birth(req.birth_data)
    day = req.date or utc_now().astimezone(E.tzinfo(req.tz)).date()
    pos = H._positions_for(day.isoformat(), req.tz)["pos"]
    moon_sign = int(chart.planets["Moon"].longitude / 30) % 12
    asc_sign = chart.ascendant["sign_index"]
    from_moon = T.gochar(pos, moon_sign)
    from_lagna = T.gochar(pos, asc_sign)
    scores = H.area_scores(from_moon)
    ss = T.sade_sati_timeline(moon_sign, datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc))
    return {
        "date": day.isoformat(),
        "natal": {"moon_sign": chart.planets["Moon"].sign, "lagna": chart.ascendant["sign"],
                  "nakshatra": chart.nakshatra_moon.name},
        "mood": H.mood_for(scores["overall"]), "scores": scores,
        "from_moon": list(from_moon.values()),
        "from_lagna": [{"planet": g["planet"], "house": g["house"], "sign": g["sign"]} for g in from_lagna.values()],
        "sade_sati": {"active": bool(ss["current"] and ss["current"]["type"] == "sade_sati"), "current": ss["current"]},
        "note": "Gochar is traditionally read from the natal Moon; Lagna-based houses are shown for reference.",
    }


@router.post("/sade-sati")
async def sade_sati(req: BirthOnlyRequest) -> dict:
    """Sade Sati and Dhaiya phases with dates, past and future."""
    chart = chart_from_birth(req.birth_data)
    moon_sign = int(chart.planets["Moon"].longitude / 30) % 12
    return T.sade_sati_timeline(moon_sign, utc_now(), span_years=35)


@router.get("/events")
async def events(
    start: date | None = Query(None, description="Start date (defaults to today)"),
    days: int = Query(30, ge=1, le=400),
    planets: str | None = Query(None, description="Comma-separated, e.g. Saturn,Jupiter,Rahu"),
    tz: str = Query("Asia/Kolkata"),
) -> dict:
    """Upcoming sign changes, retrograde/direct turns and new/full moons."""
    valid_tz(tz)
    chosen = None
    if planets:
        chosen = tuple(p.strip().title() for p in planets.split(",") if p.strip())
        bad = [p for p in chosen if p not in _PLANETS]
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown planet(s): {', '.join(bad)}")
    first = start or utc_now().astimezone(E.tzinfo(tz)).date()
    begin = datetime.combine(first, datetime.min.time(), tzinfo=E.tzinfo(tz)).astimezone(timezone.utc)
    evs = T.upcoming_events(begin, days, chosen)
    return {"start": first.isoformat(), "days": days, "events": [T.event_to_dict(e, tz) for e in evs]}

