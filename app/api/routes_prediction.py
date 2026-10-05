"""Prediction routes — topic-specific AI astrology analysis."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from groq import APIStatusError

from app.agents.singleton import get_orchestrator
from app.llm.provider import LLMBusyError
from app.models.api import PredictionRequest
from app.security.auth import require_api_key
from app.security.identity import AuthUser, ai_user
from app.services.metering import charge_ai_call, refund_ai_call

logger = structlog.get_logger()
router = APIRouter(prefix="/api/prediction", tags=["prediction"])


@router.post("/", response_model=dict, dependencies=[Depends(require_api_key)])
async def get_prediction(request: PredictionRequest, http: Request, user: AuthUser | None = Depends(ai_user)) -> dict:
    """
    Full AI prediction for a specific life topic.

    Pipeline: birth_data → kundli → rules → RAG → LLM → verify → response
    """
    orchestrator = get_orchestrator()
    meter = await charge_ai_call(user, http)
    try:
        result = await orchestrator.run(
            user_input=f"Give a detailed {request.topic} analysis for my chart",
            birth_data=request.birth_data.model_dump(),
            topic_hint=request.topic,
            language=request.language,
        )
    except (APIStatusError, LLMBusyError) as exc:
        await refund_ai_call(meter)
        # Provider rate/size limits: keep details (org id, quotas) server-side.
        logger.error("prediction_llm_error", status=getattr(exc, "status_code", None), error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="The AI service is busy right now. Please try again in a minute.",
        ) from exc
    except Exception as exc:
        await refund_ai_call(meter)
        logger.error("prediction_failed", error=str(exc))
        raise HTTPException(
            status_code=500, detail="Prediction failed. Please try again."
        ) from exc

    return result


@router.get("/topics")
async def list_topics() -> dict:
    """List all supported prediction topics."""
    return {
        "topics": [
            {"id": "career",       "label": "Career & Profession",     "icon": "💼"},
            {"id": "marriage",     "label": "Marriage & Relationships", "icon": "💍"},
            {"id": "finance",      "label": "Finance & Wealth",         "icon": "💰"},
            {"id": "education",    "label": "Education & Learning",     "icon": "📚"},
            {"id": "health",       "label": "Health & Wellbeing",       "icon": "🏥"},
            {"id": "children",     "label": "Children & Progeny",       "icon": "👶"},
            {"id": "property",     "label": "Property & Real Estate",   "icon": "🏠"},
            {"id": "travel",       "label": "Travel & Foreign",         "icon": "✈️"},
            {"id": "spirituality", "label": "Spirituality & Dharma",    "icon": "🕉️"},
            {"id": "general",      "label": "General Life Analysis",    "icon": "⭐"},
        ]
    }
