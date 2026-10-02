"""Kundli API routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.agents.singleton import get_orchestrator
from app.astrology.engine import AstrologyEngine
from app.models.api import (
    KundliMatchRequest,
    KundliRequest,
    KundliResponse,
    PlanetInfo,
    HouseInfo,
    PredictionRequest,
    PredictionResponse,
)
from app.config import get_settings

router = APIRouter(prefix="/api/kundli", tags=["kundli"])
_settings = get_settings()


def _build_chart(request: KundliRequest):
    engine = AstrologyEngine(ayanamsa=request.ayanamsa)
    try:
        dt = datetime.fromisoformat(f"{request.date_of_birth}T{request.time_of_birth}:00")
        chart = engine.calculate_chart(
            dt=dt, lat=request.latitude, lon=request.longitude, tz=request.timezone
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Chart calculation failed: {exc}") from exc
    return chart


def _navamsha_dict(div: dict) -> dict:
    return {pname: {"sign": pos.sign, "dignity": pos.dignity} for pname, pos in div.items()}


@router.post("/create", response_model=KundliResponse)
async def create_kundli(request: KundliRequest) -> KundliResponse:
    """Full natal chart with all extended calculations."""
    chart = _build_chart(request)
    return KundliResponse(
        name=request.name,
        ascendant=chart.ascendant,
        planets={
            name: PlanetInfo(
                sign=p.sign, degree=p.sign_degree, house=p.house,
                nakshatra=p.nakshatra, nakshatra_pada=p.nakshatra_pada,
                nakshatra_lord=p.nakshatra_lord,
                retrograde=p.retrograde, combust=p.combust,
                dignity=p.dignity, dignity_score=p.dignity_score,
            )
            for name, p in chart.planets.items()
        },
        houses=[
            HouseInfo(number=h.number, sign=h.sign, lord=h.lord, occupants=h.occupants)
            for h in chart.houses
        ],
        nakshatra_moon={
            "name": chart.nakshatra_moon.name,
            "pada": chart.nakshatra_moon.pada,
            "lord": chart.nakshatra_moon.lord,
            "index": chart.nakshatra_moon.index,
        },
        yogas=chart.yogas,
        current_dasha=chart.current_dasha,
        doshas=chart.doshas,
        navamsha=_navamsha_dict(chart.navamsha),
        d3=_navamsha_dict(chart.d3),
        d7=_navamsha_dict(chart.d7),
        d10=_navamsha_dict(chart.d10),
        d12=_navamsha_dict(chart.d12),
        aspects=chart.aspects,
        functional_nature=chart.functional_nature,
        ashtakavarga=chart.ashtakavarga,
        jaimini_karakas=chart.jaimini_karakas,
        shadbala=chart.shadbala,
        yogini_dasha=chart.yogini_dasha,
    )


@router.post("/match")
async def match_kundli(request: KundliMatchRequest) -> dict:
    """
    Ashtakoota Guna Milan (kundli matching).
    Returns breakdown of all 8 kootas and total score out of 36.
    """
    engine = AstrologyEngine(ayanamsa=request.ayanamsa)
    try:
        from app.astrology.engine import AstrologyEngine as AE
        def get_moon_nak_sign(bd):
            dt = datetime.fromisoformat(f"{bd.date_of_birth}T{bd.time_of_birth}:00")
            chart = engine.calculate_chart(dt=dt, lat=bd.latitude, lon=bd.longitude, tz=bd.timezone)
            moon_lon = chart.planets["Moon"].longitude
            nak_idx  = int(moon_lon / (360.0 / 27.0)) % 27
            sign_idx = int(moon_lon / 30) % 12
            return nak_idx, sign_idx, chart.nakshatra_moon.name

        nak1, sign1, nak_name1 = get_moon_nak_sign(request.person1)
        nak2, sign2, nak_name2 = get_moon_nak_sign(request.person2)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Chart calculation failed: {exc}") from exc

    from app.astrology.constants import SIGNS
    result = engine.calculate_kundli_match(nak1, sign1, nak2, sign2)
    return {
        **result,
        "person1": {
            "name": request.person1.name,
            "moon_nakshatra": nak_name1,
            "moon_sign": SIGNS[sign1],
        },
        "person2": {
            "name": request.person2.name,
            "moon_nakshatra": nak_name2,
            "moon_sign": SIGNS[sign2],
        },
    }


@router.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest) -> dict:
    """Full AI prediction pipeline for a topic."""
    orchestrator = get_orchestrator()
    result = await orchestrator.run(
        user_input=f"Give me a detailed {request.topic} analysis",
        birth_data=request.birth_data.model_dump(),
        topic_hint=request.topic,
    )
    return result
