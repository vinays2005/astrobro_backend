"""
API integration tests — tests the full HTTP layer.
LLM calls are mocked so these run without Ollama/Groq.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app
from app.security.auth import require_api_key


async def _no_auth() -> None:
    """Override require_api_key so tests don't need a real API key."""
    return


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = _no_auth
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


class TestHealth:
    async def test_health_returns_ok(self, client: AsyncClient):
        r = await client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "llm_connected" in data        # was ollama_connected before Groq migration
        assert "vector_db_chunks" in data

    async def test_root_returns_message(self, client: AsyncClient):
        r = await client.get("/")
        assert r.status_code == 200
        assert "AstroBro" in r.json()["message"]


class TestKundliCreate:
    _VALID_PAYLOAD = {
        "name": "Test User",
        "date_of_birth": "1990-08-15",
        "time_of_birth": "14:30",
        "timezone": "Asia/Kolkata",
        "latitude": 19.0760,
        "longitude": 72.8777,
    }

    async def test_create_kundli_success(self, client: AsyncClient):
        r = await client.post("/api/kundli/create", json=self._VALID_PAYLOAD)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Test User"
        assert "ascendant" in data
        assert "planets" in data
        assert "Sun" in data["planets"]
        assert "Moon" in data["planets"]
        assert len(data["houses"]) == 12

    async def test_create_kundli_invalid_date(self, client: AsyncClient):
        payload = {**self._VALID_PAYLOAD, "date_of_birth": "not-a-date"}
        r = await client.post("/api/kundli/create", json=payload)
        assert r.status_code == 422  # Pydantic validation

    async def test_create_kundli_latitude_out_of_range(self, client: AsyncClient):
        payload = {**self._VALID_PAYLOAD, "latitude": 999.0}
        r = await client.post("/api/kundli/create", json=payload)
        assert r.status_code == 422

    async def test_kundli_has_all_nine_planets(self, client: AsyncClient):
        r = await client.post("/api/kundli/create", json=self._VALID_PAYLOAD)
        assert r.status_code == 200
        planets = r.json()["planets"]
        expected = {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}
        assert expected <= set(planets.keys())

    async def test_kundli_has_current_dasha(self, client: AsyncClient):
        r = await client.post("/api/kundli/create", json=self._VALID_PAYLOAD)
        assert r.status_code == 200
        dasha = r.json()["current_dasha"]
        assert dasha.get("mahadasha") is not None
        assert "lord" in dasha["mahadasha"]


class TestPredictionTopics:
    async def test_list_topics(self, client: AsyncClient):
        r = await client.get("/api/prediction/topics")
        assert r.status_code == 200
        topics = r.json()["topics"]
        assert len(topics) == 10
        ids = [t["id"] for t in topics]
        assert "career" in ids
        assert "marriage" in ids

    async def test_predict_requires_birth_data(self, client: AsyncClient):
        r = await client.post("/api/prediction/", json={"topic": "career"})
        assert r.status_code == 422  # missing birth_data


class TestBooksEndpoints:
    async def test_list_books_returns_dict(self, client: AsyncClient):
        r = await client.get("/api/books/list")
        assert r.status_code == 200
        data = r.json()
        assert "total_chunks" in data
        assert "books" in data


class TestChatEndpoint:
    async def test_chat_requires_question(self, client: AsyncClient):
        r = await client.post("/api/chat/", json={})
        assert r.status_code == 422  # question is required

    async def test_chat_with_mocked_llm(self, client: AsyncClient):
        """Chat works end-to-end with mocked LLM (no Ollama needed)."""
        mock_response = {
            "answer": "Your Saturn Mahadasha indicates a period of discipline and karmic learning.",
            "topic": "career",
            "sources": [],
            "follow_up_questions": ["How long will Saturn Mahadasha last?"],
        }

        with patch(
            "app.api.routes_chat.get_orchestrator",
            return_value=type("O", (), {"run": AsyncMock(
                return_value={**mock_response, "request_id": "test-123", "errors": []}
            )})(),
        ):
            r = await client.post("/api/chat/", json={
                "question": "How is my career this year?",
                "birth_data": {
                    "name": "Test",
                    "date_of_birth": "1990-08-15",
                    "time_of_birth": "14:30",
                    "timezone": "Asia/Kolkata",
                    "latitude": 19.0760,
                    "longitude": 72.8777,
                },
            })
            assert r.status_code == 200
            data = r.json()
            assert "answer" in data or "request_id" in data
