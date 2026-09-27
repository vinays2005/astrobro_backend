"""Prediction routes — topic-specific AI astrology analysis."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agents.orchestrator import AgentOrchestrator
from app.models.api import PredictionRequest, PredictionResponse

router = APIRouter(prefix="/api/prediction", tags=["prediction"])


@router.post("/", response_model=dict)
async def get_prediction(request: PredictionRequest) -> dict:
    """
    Full AI prediction for a specific life topic.

    Pipeline: birth_data → kundli → rules → RAG → LLM → verify → response
    """
    orchestrator = AgentOrchestrator()
    try:
        result = await orchestrator.run(
            user_input=f"Give a detailed {request.topic} analysis for my chart",
            birth_data=request.birth_data.model_dump(),
            topic_hint=request.topic,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {exc}") from exc

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
