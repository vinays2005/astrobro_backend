"""Topic routing of knowledge-base searches: Vedic questions never see specialist or off-tradition books."""
from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rank_bm25 import BM25Okapi

from app.agents.orchestrator import AgentOrchestrator
from app.rag.retrieval import HybridRetriever
from app.rag.scope import DEFAULT, DOMAINS, HIDDEN_TITLES, Scope, _ROUTES, scope_for

AXES = {"saturn": 0, "tarot": 1, "vastu": 2, "festival": 3, "number": 4}
HIDDEN = HIDDEN_TITLES[0]


class FakeEmbedder:
    """One vector axis per topic word, so which chunks match a query is obvious."""

    def embed(self, texts):
        for text in texts:
            v = np.zeros(len(AXES), dtype=np.float32)
            for word, axis in AXES.items():
                if word in text.lower():
                    v[axis] = 1.0
            if not v.any():
                v[0] = 1.0
            yield v / np.linalg.norm(v)


MAIN = [
    (1, "Saturn transit over the Moon (sade sati) lasts seven and a half years", {"book": "Brihat Jataka"}),
    (2, "Saturn in Hellenistic astrology is the greater malefic", {"book": HIDDEN}),
    (3, "Vastu: the kitchen belongs in the south-east, says the Samhita", {"book": "Brihat Samhita"}),
    (4, "Festival muhurta: Holi falls on Phalguna purnima", {"book": "Muhurta Chintamani"}),
]
SPECIALIST = [
    (11, "The Tower tarot card means sudden upheaval", {"book": "Pictorial Key to the Tarot", "domain": "tarot"}),
    (12, "Vastu of a house: site and directions in the Essay on architecture", {"book": "Essay on Architecture", "domain": "vastu"}),
    (13, "Festival of Diwali and Lakshmi puja", {"book": "Hindu Holidays", "domain": "festivals"}),
    (14, "The number seven in the Kabala of numbers", {"book": "Kabala of Numbers", "domain": "numerology"}),
    (15, "Saturn in the Agni Purana", {"book": "Agni Purana", "domain": "lore"}),
]


def _fill(client: QdrantClient, name: str, rows) -> None:
    emb = FakeEmbedder()
    client.create_collection(name, vectors_config=VectorParams(size=len(AXES), distance=Distance.COSINE))
    client.upsert(name, points=[
        PointStruct(id=i, vector=next(emb.embed([text])).tolist(), payload={**meta, "text": text})
        for i, text, meta in rows
    ])


@pytest.fixture
def retriever() -> HybridRetriever:
    r = object.__new__(HybridRetriever)       # skip __init__: no model download, no network
    r._embedder = FakeEmbedder()
    r._qdrant = QdrantClient(":memory:")
    r._collection_name = "main"
    r._specialist_collection = "specialist"
    r._bm25, r._bm25_docs = None, []
    _fill(r._qdrant, "main", MAIN)
    _fill(r._qdrant, "specialist", SPECIALIST)
    return r


def books(chunks) -> set[str]:
    return {c.metadata["book"] for c in chunks}


class TestRetrievalScope:
    async def test_default_scope_hides_off_tradition_titles_and_specialist_books(self, retriever):
        res = await retriever.retrieve("saturn transit", top_k=10, rerank_top_k=10, scope=DEFAULT)
        assert books(res) == {"Brihat Jataka", "Brihat Samhita", "Muhurta Chintamani"}
        assert res[0].metadata["book"] == "Brihat Jataka"

    async def test_without_a_scope_nothing_is_filtered_and_specialist_books_are_not_read(self, retriever):
        res = await retriever.retrieve("saturn transit", top_k=10, rerank_top_k=10)
        assert HIDDEN in books(res) and not books(res) & {c[2]["book"] for c in SPECIALIST}

    async def test_tarot_questions_read_only_tarot_books(self, retriever):
        res = await retriever.retrieve("what does the tarot tower card mean", top_k=10, rerank_top_k=10,
                                       scope=Scope(general=False, domains=("tarot",)))
        assert books(res) == {"Pictorial Key to the Tarot"}

    async def test_vastu_questions_read_vedic_books_plus_vastu_and_lore(self, retriever):
        res = await retriever.retrieve("vastu kitchen direction", top_k=10, rerank_top_k=10,
                                       scope=Scope(domains=("vastu", "lore")))
        assert books(res) == {"Brihat Jataka", "Brihat Samhita", "Muhurta Chintamani", "Essay on Architecture", "Agni Purana"}
        assert HIDDEN not in books(res)

    async def test_specialist_chunks_compete_with_general_ones_on_score(self, retriever):
        res = await retriever.retrieve("vastu", top_k=10, rerank_top_k=10, scope=Scope(domains=("vastu",)))
        assert {res[0].metadata["book"], res[1].metadata["book"]} == {"Brihat Samhita", "Essay on Architecture"}

    async def test_a_missing_specialist_collection_is_skipped(self, retriever):
        retriever._qdrant.delete_collection("specialist")
        general_plus = await retriever.retrieve("vastu", top_k=10, rerank_top_k=10, scope=Scope(domains=("vastu",)))
        assert books(general_plus) == {"Brihat Jataka", "Brihat Samhita", "Muhurta Chintamani"}
        assert await retriever.retrieve("tarot", top_k=10, rerank_top_k=10, scope=Scope(general=False, domains=("tarot",))) == []

    async def test_a_failing_main_collection_still_fails_loudly(self, retriever):
        retriever._collection_name = "does-not-exist"
        with pytest.raises(Exception):
            await retriever.retrieve("saturn", top_k=5, rerank_top_k=5, scope=DEFAULT)

    async def test_no_specialist_collection_configured(self, retriever):
        retriever._specialist_collection = ""
        res = await retriever.retrieve("tarot", top_k=10, rerank_top_k=10, scope=Scope(general=False, domains=("tarot",)))
        assert res == []

    async def test_keyword_search_also_hides_off_tradition_titles(self, retriever):
        docs = [
            {"text": "hellenistic saturn doctrine", "metadata": {"book": HIDDEN}, "id": "a"},
            {"text": "vedic saturn transit", "metadata": {"book": "Brihat Jataka"}, "id": "b"},
            {"text": "kitchen directions", "metadata": {"book": "Brihat Samhita"}, "id": "c"},
            {"text": "holi purnima muhurta", "metadata": {"book": "Muhurta Chintamani"}, "id": "d"},
        ]
        retriever._bm25_docs = docs
        retriever._bm25 = BM25Okapi([d["text"].split() for d in docs])
        res = await retriever.retrieve("hellenistic doctrine", top_k=10, rerank_top_k=10, scope=DEFAULT)
        assert HIDDEN not in books(res)
        assert HIDDEN in books(await retriever.retrieve("hellenistic doctrine", top_k=10, rerank_top_k=10))


class TestRouting:
    @pytest.mark.parametrize("question,expected", [
        ("What does the Tower tarot card mean?", Scope(general=False, domains=("tarot",))),
        ("What is my lucky number? I want numerology", Scope(general=False, domains=("numerology",))),
        ("Is a north facing main entrance good as per vastu?", Scope(domains=("vastu", "lore"))),
        ("Which date is auspicious for griha pravesh", Scope(domains=("festivals", "calendar", "lore"))),
        ("When is the next ekadashi and what is today's panchang", Scope(domains=("festivals", "calendar", "lore"))),
        ("What is the story behind Diwali and how is it celebrated?", Scope(domains=("festivals", "calendar", "lore"))),
        ("Why do we play Holi and what is Holika Dahan?", Scope(domains=("festivals", "calendar", "lore"))),
        ("Tell me about Karwa Chauth", Scope(domains=("festivals", "calendar", "lore"))),
        ("Is a holistic approach to holidays good for my career?", DEFAULT),
        ("Which gemstone remedy suits Saturn", Scope(domains=("lore",))),
        ("When will I get a promotion in my job?", DEFAULT),
        ("tell me about my marriage prospects", DEFAULT),
        ("I want to end my life", DEFAULT),
        ("", DEFAULT),
        ("asdf qwer", DEFAULT),
    ])
    def test_questions_are_routed_by_topic(self, question, expected):
        assert scope_for(question) == expected

    def test_routes_only_name_known_domains(self):
        assert all(set(s.domains) <= set(DOMAINS) for s in _ROUTES.values())

    def test_hidden_titles_are_unique(self):
        assert len(set(HIDDEN_TITLES)) == len(HIDDEN_TITLES)


class FakeRetriever:
    def __init__(self):
        self.scopes = []

    async def retrieve(self, query, top_k=20, rerank_top_k=5, metadata_filter=None, scope=None):
        self.scopes.append(scope)
        return []


class FakeLLM:
    async def generate(self, prompt, system=None, temperature=0.3, max_tokens=2048, json_mode=False):
        return '{"answer": "ok"}'

    async def generate_stream(self, prompt, system=None, temperature=0.3, max_tokens=2048):
        yield "ok"


class TestOrchestratorUsesTheScope:
    @pytest.fixture
    def orch(self):
        o = AgentOrchestrator(engine=object(), llm=FakeLLM(), retriever=FakeRetriever(), rules=object())
        return o

    async def test_chat_routes_each_question(self, orch):
        await orch.run("What does the Tower tarot card mean?", force_chat=True)
        await orch.run("When will I get a promotion in my job?", force_chat=True)
        assert orch._retriever.scopes == [Scope(general=False, domains=("tarot",)), DEFAULT]

    async def test_streaming_chat_routes_too(self, orch):
        tokens = [t async for t in orch.run_chat_stream("Is a north facing house good as per vastu?")]
        assert tokens == ["ok"]
        assert orch._retriever.scopes == [Scope(domains=("vastu", "lore"))]
