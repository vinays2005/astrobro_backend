"""Kundli API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agents.singleton import get_orchestrator
from app.astrology.engine import AstrologyEngine
from app.models.api import (
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


@router.post("/create", response_model=KundliResponse)
async def create_kundli(request: KundliRequest) -> KundliResponse:
    """
    Create a Kundli from birth data.
    Pure deterministic calculation — LLM NOT involved.
    """
    engine = AstrologyEngine(ayanamsa=request.ayanamsa)
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(
            f"{request.date_of_birth}T{request.time_of_birth}:00"
        )
        chart = engine.calculate_chart(
            dt=dt,
            lat=request.latitude,
            lon=request.longitude,
            tz=request.timezone,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Chart calculation failed: {exc}") from exc

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
        },
        yogas=chart.yogas,
        current_dasha=chart.current_dasha,
    )


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
