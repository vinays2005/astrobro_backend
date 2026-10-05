"""Shubh Muhurat API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import valid_tz
from app.astrology import muhurat as M
from app.models.features import MuhuratRequest
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/muhurat", tags=["muhurat"], dependencies=[Depends(require_api_key)])


@router.get("/types")
async def types() -> dict:
    return {"events": M.event_types()}


@router.post("/find")
async def find(req: MuhuratRequest) -> dict:
    """Ranked auspicious days and time windows for an event (max range 150 days)."""
    valid_tz(req.timezone)
    try:
        return M.find(req.event, req.start_date, req.end_date, req.latitude, req.longitude, req.timezone,
                      include_excluded=req.include_excluded, relaxed=req.relaxed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
