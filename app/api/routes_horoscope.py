"""Horoscope API: sign-based forecasts (free, deterministic) and personalised forecasts from a birth chart."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.common import chart_from_birth, utc_now, valid_tz
from app.astrology import horoscope as H
from app.astrology import personal as PS
from app.astrology.constants import SIGNS
from app.models.features import PersonalHoroscopeRequest
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/horoscope", tags=["horoscope"], dependencies=[Depends(require_api_key)])


@router.get("/all")
async def all_signs(
    period: str = Query("today", pattern="^(today|tomorrow)$"),
    tz: str = Query("Asia/Kolkata"),
) -> dict:
    """One-line summary for every Moon sign (home-screen overview)."""
    valid_tz(tz)
    out = []
    for i in range(12):
        f = H.forecast(SIGNS[i], period, None, tz)
        out.append({"sign": f["sign"], "date": f["date"], "mood": f["mood"], "overall": f["scores"]["overall"],
                    "summary": f["summary"], "lucky_numbers": f["lucky"]["numbers"], "lucky_colour": f["lucky"]["colour"]})
    return {"period": period, "signs": out, "note": "Horoscopes are read by Moon sign (Rashi)."}


@router.get("/{sign}")
async def sign_horoscope(
    sign: str,
    period: str = Query("today", pattern="^(today|tomorrow|daily|weekly|monthly|yearly)$"),
    on: date | None = Query(None, alias="date", description="Anchor date (YYYY-MM-DD); defaults to today"),
    tz: str = Query("Asia/Kolkata"),
) -> dict:
    """Horoscope for a Moon sign. English or Sanskrit names work (e.g. Aries or Mesha)."""
    valid_tz(tz)
    try:
        return H.forecast(sign, period, on, tz)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/personal")
async def personal_horoscope(req: PersonalHoroscopeRequest) -> dict:
    """Forecast personalised with your Moon sign, Chandra/Tara Bala, running Dasha and Sade Sati."""
    valid_tz(req.tz)
    chart = chart_from_birth(req.birth_data)
    return PS.personal_forecast(chart, req.period, req.date, req.tz, utc_now())

