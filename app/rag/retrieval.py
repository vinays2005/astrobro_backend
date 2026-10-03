"""
Hybrid retrieval: dense (vector) + sparse (BM25) + reranking.

Data pipeline:
  query → [vector search | BM25 search] → RRF merge → rerank → top-K chunks
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    score: float
    source: str  # "vector" | "bm25" | "reranked"


class HybridRetriever:
    """
    Combines dense and sparse retrieval with optional cross-encoder reranking.

    All errors fail loud — never return fabricated evidence.
    """

    def __init__(
        self,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        reranker_model: str = "",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        collection_name: str = "vedic_books",
        embedding_dimension: int = 384,
        reranker_enabled: bool = False,
    ) -> None:
        # fastembed uses ONNX Runtime (~80 MB) instead of PyTorch (~400 MB).
        # Drop-in replacement for SentenceTransformer for vector search.
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._embedder = TextEmbedding(embedding_model)
        self._reranker_enabled = False  # CrossEncoder removed — used PyTorch
        self._reranker = None

        self._collection_name = collection_name
        self._qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None,timeout=120,)

        # Qdrant needs the collection created up front with a fixed vector
        # size/distance metric — unlike Chroma's get_or_create, so check
        # existence first (idempotent across restarts).
        if not self._qdrant.collection_exists(collection_name):
            self._qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=embedding_dimension, distance=Distance.COSINE
                ),
            )

        self._bm25: Any = None
        self._bm25_docs: list[dict[str, Any]] = []
        self._bm25_lock = __import__("threading").Lock()
        # BM25 warmup intentionally removed — scrolling 120k+ Qdrant docs at
        # startup pushes Railway's container past its memory limit (OOM kill).
        # Vector-only retrieval is used until books are re-ingested, at which
        # point add_chunks() rebuilds the BM25 index in-process.

    def _warmup_bm25(self) -> None:
        """Scroll all existing Qdrant points and build initial BM25 index (background thread)."""
        import logging
        log = logging.getLogger(__name__)
        try:
            docs: list[dict[str, Any]] = []
            offset = None
            while True:
                points, offset = self._qdrant.scroll(
                    collection_name=self._collection_name,
                    limit=1000,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    text = str(payload.get("text", ""))
                    meta = {k: v for k, v in payload.items() if k != "text"}
                    chunk_id = str(payload.get("chunk_id", ""))
                    docs.append({"text": text, "metadata": meta, "id": chunk_id})
                if offset is None:
                    break
            if docs:
                from rank_bm25 import BM25Okapi
                bm25 = BM25Okapi([self._tokenize(d["text"]) for d in docs])
                with self._bm25_lock:
                    self._bm25_docs = docs
                    self._bm25 = bm25
                log.info("bm25_warmup_done", docs=len(docs))
        except Exception:
            log.warning("bm25_warmup_failed — BM25 will activate after first ingest")

    # ── Indexing ──────────────────────────────────────────────

    def add_chunks(self, chunks: list[Any], batch_size: int = 64) -> None:
        """Index chunks into vector store and rebuild BM25."""
        from app.rag.ingestion import Chunk  # type: ignore[import]
        from qdrant_client.models import PointStruct

        texts = [c.text for c in chunks]
        metas = [c.metadata for c in chunks]
        ids = [c.chunk_id for c in chunks]

        for i in range(0, len(texts), batch_size):
            bt = texts[i:i + batch_size]
            bm = metas[i:i + batch_size]
            bi = ids[i:i + batch_size]
            embeddings = [emb.tolist() for emb in self._embedder.embed(bt)]

            # Qdrant point IDs must be unsigned int or UUID — our chunk_ids
            # are hex strings (sha256[:16]), so use them as a UUID5 seed to
            # get a stable, valid point ID, and stash the original chunk_id
            # in the payload for lookups/dedup elsewhere.
            import uuid
            points = [
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id)),
                    vector=emb,
                    payload={**meta, "text": text, "chunk_id": chunk_id},
                )
                for chunk_id, text, meta, emb in zip(bi, bt, bm, embeddings)
            ]
            for attempt in range(3):
                try:
                    self._qdrant.upsert(
                        collection_name=self._collection_name,
                        points=points,
                        wait=True,
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    import time
                    time.sleep(2 ** attempt)

        # Append to existing docs (don't replace) so BM25 covers all ingested books
        new_docs = [
            {"text": t, "metadata": m, "id": i}
            for t, m, i in zip(texts, metas, ids)
        ]
        from rank_bm25 import BM25Okapi
        with self._bm25_lock:
            self._bm25_docs.extend(new_docs)
            self._bm25 = BM25Okapi([self._tokenize(d["text"]) for d in self._bm25_docs])

    # ── Retrieval ─────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = 20,
        rerank_top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Hybrid retrieval: vector + BM25 → RRF merge → optional rerank.

        All CPU-bound and blocking I/O calls are offloaded to a thread pool
        via asyncio.to_thread() so the event loop stays free to serve other
        requests concurrently.
        """
        import asyncio
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        # ONNX inference is fast; run in thread to keep event loop free
        raw_emb = await asyncio.to_thread(
            lambda: list(self._embedder.embed([query]))[0]
        )
        query_emb = raw_emb.tolist()

        qfilter = None
        if metadata_filter:
            qfilter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in metadata_filter.items()
                ]
            )

        # I/O-bound: sync Qdrant HTTP call blocks the event loop — run in thread
        qdrant_result = await asyncio.to_thread(
            self._qdrant.query_points,
            collection_name=self._collection_name,
            query=query_emb,
            limit=top_k,
            query_filter=qfilter,
        )
        vec_results = qdrant_result.points

        vector_chunks: list[RetrievedChunk] = [
            RetrievedChunk(
                text=str(point.payload.get("text", "")),
                metadata={k: v for k, v in (point.payload or {}).items() if k != "text"},
                score=float(point.score),
                source="vector",
            )
            for point in vec_results
        ]

        bm25_chunks: list[RetrievedChunk] = []
        if self._bm25 is not None and self._bm25_docs:
            # CPU-bound: BM25 scores 34k docs in pure Python — run in thread
            tokenized = self._tokenize(query)
            scores = await asyncio.to_thread(self._bm25.get_scores, tokenized)
            top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            for idx in top_idx:
                if scores[idx] > 0:
                    bm25_chunks.append(RetrievedChunk(
                        text=self._bm25_docs[idx]["text"],
                        metadata=self._bm25_docs[idx]["metadata"],
                        score=float(scores[idx]),
                        source="bm25",
                    ))

        merged = self._rrf_merge(vector_chunks, bm25_chunks)

        return merged[:rerank_top_k]

    # ── Helpers ───────────────────────────────────────────────

    def _rrf_merge(
        self,
        vec: list[RetrievedChunk],
        bm25: list[RetrievedChunk],
        k: int = 60,
    ) -> list[RetrievedChunk]:
        scores: dict[str, float] = {}
        chunk_map: dict[str, RetrievedChunk] = {}

        for rank, c in enumerate(vec):
            key = c.text[:80]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            chunk_map[key] = c

        for rank, c in enumerate(bm25):
            key = c.text[:80]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in chunk_map:
                chunk_map[key] = c

        return [chunk_map[k] for k in sorted(scores, key=lambda x: scores[x], reverse=True)]

    def _tokenize(self, text: str) -> list[str]:
        return text.lower().split()