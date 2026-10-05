"""Numerology API."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.astrology import numerology as N
from app.models.features import NumerologyCompatibilityRequest, NumerologyRequest
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/numerology", tags=["numerology"], dependencies=[Depends(require_api_key)])


@router.post("/profile")
async def profile(req: NumerologyRequest) -> dict:
    """Life Path, Destiny, Soul Urge, Personality, Birthday, personal cycles and Indian Mulank/Bhagyank."""
    try:
        return N.profile(req.name.strip(), req.date_of_birth, req.date or date.today())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/compatibility")
async def compatibility(req: NumerologyCompatibilityRequest) -> dict:
    try:
        return N.compatibility(req.person1.name.strip(), req.person1.date_of_birth,
                               req.person2.name.strip(), req.person2.date_of_birth)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/daily")
async def daily(date_of_birth: date = Query(...), on: date | None = Query(None, alias="date")) -> dict:
    return N.daily_number(date_of_birth, on or date.today())
