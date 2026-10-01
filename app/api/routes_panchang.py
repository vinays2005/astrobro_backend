"""
Real Vedic Panchang API endpoint.

GET /api/panchang?date=YYYY-MM-DD&lat=&lon=&tz=
Returns all five limbs (Tithi, Vara, Nakshatra, Yoga, Karana) plus
Rahu Kaal, Yamagandam, Gulika, Choghadiya, Abhijit Muhurat, sunrise/sunset.
"""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, HTTPException, Query

from app.astrology.panchang import PanchangEngine, PanchangResult
from app.config import get_settings

router = APIRouter(prefix="/api/panchang", tags=["panchang"])
_settings = get_settings()
_engine = PanchangEngine(ayanamsa=_settings.ayanamsa)


@router.get("")
async def get_panchang(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    lat: float = Query(28.6139, description="Latitude (default: New Delhi)"),
    lon: float = Query(77.2090, description="Longitude"),
    tz: str = Query("Asia/Kolkata", description="Timezone (e.g. Asia/Kolkata)"),
) -> dict:
    """
    Real Vedic Panchang for a given date and location.

    All calculations use Swiss Ephemeris with Lahiri ayanamsa.
    Sunrise/sunset are location-specific via swe.rise_trans().
    """
    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    try:
        result: PanchangResult = _engine.calculate(target, lat, lon, tz)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Panchang calculation error: {exc}") from exc

    return _to_dict(result)


def _to_dict(p: PanchangResult) -> dict:
    return {
        "date": p.date,
        "vara": p.vara,
        "tithi": {
            "number": p.tithi.number,
            "name": p.tithi.name,
            "paksha": p.tithi.paksha,
            "end_time": p.tithi.end_time,
            "display": f"{p.tithi.paksha} {p.tithi.name}",
        },
        "nakshatra": {
            "index": p.nakshatra.index,
            "name": p.nakshatra.name,
            "lord": p.nakshatra.lord,
            "pada": p.nakshatra.pada,
            "end_time": p.nakshatra.end_time,
        },
        "yoga": {
            "index": p.yoga.index,
            "name": p.yoga.name,
            "end_time": p.yoga.end_time,
            "auspicious": p.yoga.auspicious,
        },
        "karana": {
            "name": p.karana.name,
            "end_time": p.karana.end_time,
        },
        "sun_moon": {
            "sunrise": p.sun_moon.sunrise,
            "sunset": p.sun_moon.sunset,
            "moonrise": p.sun_moon.moonrise,
            "moonset": p.sun_moon.moonset,
            "day_duration_hours": round(p.sun_moon.day_duration_hours, 2),
        },
        "inauspicious": {
            "rahu_kaal": p.rahu_kaal,
            "yamagandam": p.yamagandam,
            "gulika": p.gulika,
        },
        "muhurat": {
            "abhijit": p.abhijit_muhurat,
        },
        "choghadiya": [
            {"name": m.name, "start": m.start, "end": m.end, "quality": m.quality}
            for m in p.choghadiya
        ],
        "calendar": {
            "vikram_samvat": p.vikram_samvat,
            "shaka_samvat": p.shaka_samvat,
            "masa": p.masa,
            "ayana": p.ayana,
            "ritu": p.ritu,
        },
    }
