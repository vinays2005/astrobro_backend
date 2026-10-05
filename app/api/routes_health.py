"""Health check endpoint."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from app.agents.singleton import is_ready
from app.config import get_settings
from app.models.api import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])

# The upstream checks call Groq and Qdrant over the network and this route is public (load balancers
# poll it), so they run off the event loop and the answer is reused for a short while.
_CACHE_SECONDS = 30.0
_cache: dict = {"at": float("-inf"), "llm_ok": False, "chunks": 0}


def _probe_upstreams() -> tuple[bool, int]:
    s = get_settings()
    llm_ok = False
    chunks = 0

    try:
        if s.groq_api_key:
            from groq import Groq
            # Cheap connectivity check — lists models rather than spending tokens on a completion call.
            Groq(api_key=s.groq_api_key, timeout=5.0).models.list()
            llm_ok = True
    except Exception:
        pass

    try:
        if s.qdrant_url:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=5)
            if client.collection_exists(s.books_collection):
                chunks = client.get_collection(s.books_collection).points_count or 0
    except Exception:
        pass

    return llm_ok, chunks


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness plus AI-layer status; `ai_ready` is False while the AI orchestrator is not up."""
    now = time.monotonic()
    if now - _cache["at"] > _CACHE_SECONDS:
        llm_ok, chunks = await asyncio.to_thread(_probe_upstreams)
        _cache.update(at=now, llm_ok=llm_ok, chunks=chunks)

    return HealthResponse(
        status="ok",
        llm_connected=_cache["llm_ok"],
        vector_db_chunks=_cache["chunks"],
        ai_ready=is_ready(),
    )
