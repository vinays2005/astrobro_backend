"""Vastu Shastra API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.astrology import vastu as V
from app.models.features import VastuRequest
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/vastu", tags=["vastu"], dependencies=[Depends(require_api_key)])


@router.get("/guidelines")
async def guidelines() -> dict:
    return V.guidelines()


@router.post("/analyze")
async def analyze(req: VastuRequest) -> dict:
    """Check where rooms sit against traditional Vastu directions. Rooms: {"kitchen": "NE", "pooja_room": "SW", ...}."""
    if not req.entrance_facing and not req.rooms:
        raise HTTPException(status_code=422, detail="Provide an entrance direction or at least one room.")
    try:
        return V.analyze(req.entrance_facing, req.rooms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
