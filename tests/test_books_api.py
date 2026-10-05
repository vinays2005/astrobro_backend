"""Book index listing: fast server-side counts, a scroll fallback, and no leaked error details."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_books
from app.main import app
from app.security.auth import require_api_key


class FakeQdrant:
    """Stands in for QdrantClient; `facet_error` makes the fast path fail like an older server."""

    def __init__(self, points: list[str], facet_error: Exception | None = None, facet_limit_hit: bool = False):
        self.points = points
        self.facet_error = facet_error
        self.facet_limit_hit = facet_limit_hit
        self.scrolls = 0

    def collection_exists(self, name):
        return True

    def get_collection(self, name):
        return SimpleNamespace(points_count=len(self.points))

    def facet(self, collection_name, key, limit, exact):
        if self.facet_error:
            raise self.facet_error
        counts: dict[str, int] = {}
        for p in self.points:
            counts[p] = counts.get(p, 0) + 1
        hits = [SimpleNamespace(value=v, count=c) for v, c in counts.items()]
        return SimpleNamespace(hits=hits * limit if self.facet_limit_hit else hits)

    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        self.scrolls += 1
        start = offset or 0
        page = self.points[start:start + limit]
        nxt = start + limit if start + limit < len(self.points) else None
        return [SimpleNamespace(payload={"book": b}) for b in page], nxt


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    routes_books._invalidate_books_cache()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    routes_books._invalidate_books_cache()
    app.dependency_overrides.clear()


POINTS = ["Brihat Jataka"] * 3 + ["Waite Tarot"] * 2 + ["Agni Purana"]


class TestCountBooks:
    def test_uses_the_server_side_facet_when_available(self):
        fake = FakeQdrant(POINTS)
        with patch("qdrant_client.QdrantClient", return_value=fake):
            r = routes_books._count_books()
        assert r["total_chunks"] == 6
        assert r["books"] == [{"title": "Agni Purana", "chunks": 1}, {"title": "Brihat Jataka", "chunks": 3},
                              {"title": "Waite Tarot", "chunks": 2}]
        assert fake.scrolls == 0

    @pytest.mark.parametrize("fake", [
        FakeQdrant(POINTS, facet_error=RuntimeError("Index required but not found")),   # no index / old server
        FakeQdrant(POINTS, facet_limit_hit=True),                                        # page full: list may be cut short
    ])
    def test_falls_back_to_scrolling_with_the_same_result(self, fake):
        with patch("qdrant_client.QdrantClient", return_value=fake):
            r = routes_books._count_books()
        assert fake.scrolls >= 1
        assert {b["title"]: b["chunks"] for b in r["books"]} == {"Brihat Jataka": 3, "Waite Tarot": 2, "Agni Purana": 1}
        assert r["total_chunks"] == 6

    def test_scroll_pages_through_every_point(self):
        fake = FakeQdrant(["A"] * 2500 + ["B"] * 10, facet_error=RuntimeError("no facet"))
        with patch("qdrant_client.QdrantClient", return_value=fake):
            r = routes_books._count_books()
        assert fake.scrolls == 3
        assert {b["title"]: b["chunks"] for b in r["books"]} == {"A": 2500, "B": 10}


class TestListEndpoint:
    async def test_result_is_cached_between_calls(self, client):
        with patch.object(routes_books, "_count_books", return_value={"total_chunks": 1, "books": []}) as counted:
            assert (await client.get("/api/books/list")).json()["total_chunks"] == 1
            assert (await client.get("/api/books/list")).status_code == 200
        assert counted.call_count == 1

    async def test_vector_db_errors_do_not_leak_details(self, client):
        boom = RuntimeError("connect to https://secret-cluster.qdrant.io failed: api-key=abc123")
        with patch.object(routes_books, "_count_books", side_effect=boom):
            r = await client.get("/api/books/list")
        assert r.status_code == 502
        assert "secret-cluster" not in r.text and "abc123" not in r.text
