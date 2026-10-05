"""Shared helpers for the feature routers."""
from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone

from fastapi import HTTPException

from app.astrology.engine import AstrologyEngine, Chart
from app.models.api import BirthData


def valid_tz(tz: str) -> str:
    try:
        zoneinfo.ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Unknown timezone '{tz}'. Use an IANA name such as Asia/Kolkata.") from None
    return tz


def chart_from_birth(birth: BirthData, ayanamsa: str = "LAHIRI") -> Chart:
    """Build a natal chart; failures become a clean 400 without internals."""
    try:
        hh, mm = (birth.time_of_birth.split(":") + ["0"])[:2]
        dt = datetime.fromisoformat(f"{birth.date_of_birth}T{int(hh):02d}:{int(mm):02d}:00")
        return AstrologyEngine(ayanamsa=ayanamsa).calculate_chart(
            dt=dt, lat=birth.latitude, lon=birth.longitude, tz=birth.timezone
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Could not calculate a chart from these birth details.") from None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
