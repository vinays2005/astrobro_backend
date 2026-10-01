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
        embedding_model: str = "all-MiniLM-L6-v2",
        reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        collection_name: str = "vedic_books",
        embedding_dimension: int = 384,
        reranker_enabled: bool = True,
    ) -> None:
        from sentence_transformers import SentenceTransformer
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._embedder = SentenceTransformer(embedding_model)
        self._reranker_enabled = reranker_enabled
        self._reranker = None
        if reranker_enabled:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(reranker_model)

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
            embeddings = self._embedder.encode(bt, normalize_embeddings=True).tolist()

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

        self._bm25_docs = [
            {"text": t, "metadata": m, "id": i}
            for t, m, i in zip(texts, metas, ids)
        ]
        from rank_bm25 import BM25Okapi
        self._bm25 = BM25Okapi([self._tokenize(t) for t in texts])

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

        # CPU-bound: SentenceTransformer inference blocks the GIL — run in thread
        raw_emb = await asyncio.to_thread(
            self._embedder.encode, [query], normalize_embeddings=True
        )
        query_emb = raw_emb.tolist()[0]

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

        if self._reranker_enabled and self._reranker is not None and merged:
            pairs = [(query, c.text) for c in merged[:top_k]]
            # CPU-bound: CrossEncoder inference — run in thread
            rerank_scores = await asyncio.to_thread(self._reranker.predict, pairs)
            for chunk, score in zip(merged[:top_k], rerank_scores):
                chunk.score = float(score)
                chunk.source = "reranked"
            merged.sort(key=lambda c: c.score, reverse=True)

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