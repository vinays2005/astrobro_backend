"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from app.models.api import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check system health — Ollama + vector DB connectivity."""
    ollama_ok = False
    chroma_count = 0

    try:
        import ollama
        client = ollama.Client()
        client.list()
        ollama_ok = True
    except Exception:
        pass

    try:
        import chromadb
        from app.config import get_settings
        s = get_settings()
        db = chromadb.PersistentClient(path=s.chroma_persist_dir)
        col = db.get_or_create_collection(s.books_collection)
        chroma_count = col.count()
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        ollama_connected=ollama_ok,
        vector_db_chunks=chroma_count,
    )
