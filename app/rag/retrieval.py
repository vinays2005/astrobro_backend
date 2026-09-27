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
        persist_dir: str = "./data/chroma",
        collection_name: str = "vedic_books",
        reranker_enabled: bool = True,
    ) -> None:
        from sentence_transformers import SentenceTransformer
        import chromadb

        self._embedder = SentenceTransformer(embedding_model)
        self._reranker_enabled = reranker_enabled
        self._reranker = None
        if reranker_enabled:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(reranker_model)

        self._chroma = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._chroma.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        self._bm25: Any = None
        self._bm25_docs: list[dict[str, Any]] = []

    # ── Indexing ──────────────────────────────────────────────

    def add_chunks(self, chunks: list[Any], batch_size: int = 256) -> None:
        """Index chunks into vector store and rebuild BM25."""
        from app.rag.ingestion import Chunk  # type: ignore[import]
        texts = [c.text for c in chunks]
        metas = [c.metadata for c in chunks]
        ids = [c.chunk_id for c in chunks]

        for i in range(0, len(texts), batch_size):
            bt = texts[i:i + batch_size]
            bm = metas[i:i + batch_size]
            bi = ids[i:i + batch_size]
            embeddings = self._embedder.encode(bt, normalize_embeddings=True).tolist()
            self._collection.upsert(ids=bi, documents=bt, metadatas=bm, embeddings=embeddings)

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
        """Hybrid retrieval: vector + BM25 → RRF merge → optional rerank."""
        query_emb = self._embedder.encode([query], normalize_embeddings=True).tolist()

        where = metadata_filter if metadata_filter else None
        vec_results = self._collection.query(
            query_embeddings=query_emb,
            n_results=min(top_k, self._collection.count() or 1),
            where=where,
        )

        vector_chunks: list[RetrievedChunk] = []
        if vec_results.get("documents"):
            for i, doc in enumerate(vec_results["documents"][0]):
                vector_chunks.append(RetrievedChunk(
                    text=doc,
                    metadata=vec_results["metadatas"][0][i],
                    score=1.0 - float(vec_results["distances"][0][i]),
                    source="vector",
                ))

        bm25_chunks: list[RetrievedChunk] = []
        if self._bm25 is not None and self._bm25_docs:
            scores = self._bm25.get_scores(self._tokenize(query))
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
            rerank_scores = self._reranker.predict(pairs)
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
