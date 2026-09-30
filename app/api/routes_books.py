"""
Book management API — upload Vedic astrology PDFs for RAG ingestion.

Data pipeline: POST PDF → save to disk → PDFIngestor → HybridRetriever.add_chunks()
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from app.config import get_settings
from app.rag.ingestion import PDFIngestor
from app.rag.retrieval import HybridRetriever
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/books", tags=["books"])
_settings = get_settings()
_MAX_PDF_MB = 50


@router.post("/ingest", dependencies=[Depends(require_api_key)])
async def ingest_book(
    file: UploadFile = File(...),
    title: str = Form(...),
    author: str = Form(default="Unknown"),
    topic_tags: str = Form(default=""),  # comma-separated
) -> dict:
    """
    Upload a Vedic astrology PDF and ingest into the vector store.

    topic_tags: comma-separated e.g. "marriage,career,planets"
    """
    # Validate MIME
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > _MAX_PDF_MB:
        raise HTTPException(status_code=413, detail=f"PDF too large: {size_mb:.1f}MB (max {_MAX_PDF_MB}MB)")

    tags = [t.strip() for t in topic_tags.split(",") if t.strip()]
    book_meta: dict = {
        "book": title,
        "author": author,
        "topic_tags": tags,
    }

    # Write to temp file — fail loud if disk write fails
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        ingestor = PDFIngestor(chunk_size=800, chunk_overlap=150)
        result = ingestor.ingest(tmp_path, book_meta=book_meta)

        if not result.chunks:
            raise HTTPException(
                status_code=422,
                detail=f"No text extracted from PDF. Pages skipped: {result.pages_skipped}. Errors: {result.errors[:3]}"
            )

        retriever = HybridRetriever(
            embedding_model=_settings.embedding_model,
            qdrant_url=_settings.qdrant_url,
            qdrant_api_key=_settings.qdrant_api_key,
            collection_name=_settings.books_collection,
            embedding_dimension=_settings.embedding_dimension,
            reranker_enabled=False,
        )
        retriever.add_chunks(result.chunks)

    finally:
        os.unlink(tmp_path)

    return {
        "success": True,
        "book": title,
        "author": author,
        "chunks_indexed": len(result.chunks),
        "pages_processed": result.pages_processed,
        "pages_skipped": result.pages_skipped,
        "errors": result.errors[:5] if result.errors else [],
    }


@router.get("/list")
async def list_books() -> dict:
    """List all books currently indexed in the vector store."""
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=_settings.qdrant_url, api_key=_settings.qdrant_api_key or None)

        if not client.collection_exists(_settings.books_collection):
            return {"total_chunks": 0, "books": []}

        info = client.get_collection(_settings.books_collection)
        total = info.points_count or 0

        # Get unique book titles from metadata — scroll through payloads
        # (Qdrant's equivalent of Chroma's .get(limit=..., include=[...]))
        books: dict[str, int] = {}
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=_settings.books_collection,
                limit=500,
                offset=offset,
                with_payload=["book"],
                with_vectors=False,
            )
            for point in points:
                book_title = str((point.payload or {}).get("book", "Unknown"))
                books[book_title] = books.get(book_title, 0) + 1
            if offset is None:
                break

        return {
            "total_chunks": total,
            "books": [{"title": t, "chunks": c} for t, c in sorted(books.items())],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector DB error: {exc}") from exc