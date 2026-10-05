"""Compatibility APIs: detailed Kundli Milan report and the Love Calculator."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.common import chart_from_birth, utc_now
from app.astrology import match_report as MR
from app.models.features import DetailedMatchRequest, LoveRequest
from app.security.auth import require_api_key

match_router = APIRouter(prefix="/api/kundli", tags=["kundli"], dependencies=[Depends(require_api_key)])
love_router = APIRouter(prefix="/api/love", tags=["love"], dependencies=[Depends(require_api_key)])


@match_router.post("/match/detailed")
async def detailed_match(req: DetailedMatchRequest) -> dict:
    """36-point Guna Milan with doshas and cancellations, Manglik, Navamsa, marriage windows and a verdict."""
    a, b = req.person1, req.person2
    if req.person1_role == "groom":
        boy_birth, girl_birth = a, b
    else:
        boy_birth, girl_birth = b, a
    boy, girl = chart_from_birth(boy_birth), chart_from_birth(girl_birth)
    return MR.full_report(boy, girl, boy_birth.name, girl_birth.name, utc_now())


@love_router.post("/calculate")
async def love_calculate(req: LoveRequest) -> dict:
    """Love Calculator: name-based score and FLAMES, plus astrological compatibility when birth details are given."""
    moon_a = moon_b = None
    if req.birth1 and req.birth2:
        moon_a = MR.moon_placement(chart_from_birth(req.birth1))
        moon_b = MR.moon_placement(chart_from_birth(req.birth2))
    return MR.love_calculation(req.name1.strip(), req.name2.strip(), moon_a, moon_b)
