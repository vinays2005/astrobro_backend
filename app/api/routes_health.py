"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from app.models.api import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check system health — Groq + vector DB connectivity."""
    llm_ok = False
    vector_count = 0

    try:
        import os
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        # Cheap connectivity check — lists models rather than spending
        # tokens on a completion call.
        client.models.list()
        llm_ok = True
    except Exception:
        pass

    try:
        from qdrant_client import QdrantClient
        from app.config import get_settings
        s = get_settings()
        client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
        if client.collection_exists(s.books_collection):
            info = client.get_collection(s.books_collection)
            vector_count = info.points_count or 0
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        llm_connected=llm_ok,
        vector_db_chunks=vector_count,
    )