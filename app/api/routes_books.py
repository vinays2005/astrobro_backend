"""
Book management API — upload Vedic astrology PDFs for RAG ingestion.

Data pipeline: POST PDF → save to disk → PDFIngestor → HybridRetriever.add_chunks()

Ingestion is done in a FastAPI BackgroundTask so the HTTP response returns
immediately (HTTP 202) before Railway's proxy timeout fires.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form

from app.config import get_settings
from app.rag.ingestion import PDFIngestor
from app.rag.retrieval import HybridRetriever
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/books", tags=["books"])
_settings = get_settings()
_MAX_PDF_MB = 200  # raised from 50 — large classical texts can be 120MB+

log = logging.getLogger(__name__)

# In-memory cache for the books list — scrolling 53k+ chunks on every request
# takes 5+ minutes. Cache for 5 minutes; invalidated automatically on new ingestion.
_books_cache: dict | None = None
_books_cache_at: float = 0.0
_BOOKS_CACHE_TTL = 300.0  # seconds


def _invalidate_books_cache() -> None:
    global _books_cache, _books_cache_at
    _books_cache = None
    _books_cache_at = 0.0

# ── Singleton retriever — reuses loaded SentenceTransformer across requests ──
_retriever_lock = threading.Lock()
_retriever: HybridRetriever | None = None


def _get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = HybridRetriever(
                    embedding_model=_settings.embedding_model,
                    qdrant_url=_settings.qdrant_url,
                    qdrant_api_key=_settings.qdrant_api_key,
                    collection_name=_settings.books_collection,
                    embedding_dimension=_settings.embedding_dimension,
                    reranker_enabled=False,
                )
    return _retriever


def _ingest_in_background(tmp_path: str, book_meta: dict) -> None:
    """Run in BackgroundTask — called after HTTP 202 is already sent."""
    _invalidate_books_cache()
    try:
        log.info("ingest_start", book=book_meta.get("book"), path=tmp_path)
        ingestor = PDFIngestor(chunk_size=800, chunk_overlap=150)
        result = ingestor.ingest(tmp_path, book_meta=book_meta)

        if not result.chunks:
            log.warning(
                "ingest_no_text",
                book=book_meta.get("book"),
                pages_skipped=result.pages_skipped,
                errors=result.errors[:3],
            )
            return

        retriever = _get_retriever()
        retriever.add_chunks(result.chunks)

        # Keep orchestrator's retriever in sync so AI chat also sees new books
        try:
            from app.agents.singleton import get_orchestrator
            get_orchestrator()._retriever.add_chunks(result.chunks)
        except Exception:
            pass
        log.info(
            "ingest_done",
            book=book_meta.get("book"),
            chunks=len(result.chunks),
            pages=result.pages_processed,
        )
    except Exception as exc:
        log.exception("ingest_error", book=book_meta.get("book"), error=str(exc))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/ingest", dependencies=[Depends(require_api_key)])
async def ingest_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    author: str = Form(default="Unknown"),
    topic_tags: str = Form(default=""),  # comma-separated
) -> dict:
    """
    Upload a Vedic astrology PDF and ingest into the vector store.

    Returns HTTP 202 immediately; actual chunking + embedding runs in a
    background task so Railway's HTTP proxy never times out.

    topic_tags: comma-separated e.g. "marriage,career,planets"
    """
    if file.content_type not in (
        "application/pdf", "application/octet-stream", "binary/octet-stream", "text/plain"
    ):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > _MAX_PDF_MB:
        raise HTTPException(
            status_code=413,
            detail=f"PDF too large: {size_mb:.1f}MB (max {_MAX_PDF_MB}MB)",
        )

    tags = [t.strip() for t in topic_tags.split(",") if t.strip()]
    book_meta: dict = {"book": title, "author": author, "topic_tags": tags}

    # Persist to a non-deleted temp file so background task can read it
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    background_tasks.add_task(_ingest_in_background, tmp_path, book_meta)

    return {
        "success": True,
        "status": "queued",
        "book": title,
        "author": author,
        "size_mb": round(size_mb, 2),
        "message": "Ingestion running in background — check /api/books/list to confirm when done",
    }


@router.get("/list")
async def list_books() -> dict:
    """List all books currently indexed in the vector store."""
    import time
    global _books_cache, _books_cache_at

    now = time.monotonic()
    if _books_cache is not None and (now - _books_cache_at) < _BOOKS_CACHE_TTL:
        return _books_cache

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=_settings.qdrant_url, api_key=_settings.qdrant_api_key or None, timeout=30)

        if not client.collection_exists(_settings.books_collection):
            return {"total_chunks": 0, "books": []}

        info = client.get_collection(_settings.books_collection)
        total = info.points_count or 0

        books: dict[str, int] = {}
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=_settings.books_collection,
                limit=1000,
                offset=offset,
                with_payload=["book"],
                with_vectors=False,
            )
            for point in points:
                book_title = str((point.payload or {}).get("book", "Unknown"))
                books[book_title] = books.get(book_title, 0) + 1
            if offset is None:
                break

        result = {
            "total_chunks": total,
            "books": [{"title": t, "chunks": c} for t, c in sorted(books.items())],
        }
        _books_cache = result
        _books_cache_at = now
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector DB error: {exc}") from exc
