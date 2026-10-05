"""LLM provider errors must not leak internals (org ids, quotas) to API clients."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from groq import APIStatusError
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.security.auth import require_api_key

_SECRET = "org_01SECRETORG limit 8000 requested 9999"


def _provider_error() -> APIStatusError:
    req = httpx.Request("POST", "https://api.groq.com/x")
    return APIStatusError(_SECRET, response=httpx.Response(429, request=req), body=None)


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=30
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


_BIRTH = {
    "name": "T", "date_of_birth": "1990-08-15", "time_of_birth": "14:30",
    "timezone": "Asia/Kolkata", "latitude": 19.076, "longitude": 72.8777,
}


class TestPredictionErrors:
    async def test_provider_error_becomes_503_without_internals(self, client):
        orch = MagicMock()
        orch.run.side_effect = _provider_error()
        with patch("app.api.routes_prediction.get_orchestrator", return_value=orch):
            r = await client.post("/api/prediction/", json={"birth_data": _BIRTH, "topic": "career"})
        assert r.status_code == 503
        assert "org_01" not in r.text and "8000" not in r.text

    async def test_unexpected_error_is_generic_500(self, client):
        orch = MagicMock()
        orch.run.side_effect = RuntimeError(_SECRET)
        with patch("app.api.routes_prediction.get_orchestrator", return_value=orch):
            r = await client.post("/api/prediction/", json={"birth_data": _BIRTH, "topic": "career"})
        assert r.status_code == 500
        assert "org_01" not in r.text


class TestChatErrors:
    async def test_provider_error_becomes_503_without_internals(self, client):
        orch = MagicMock()
        orch.run.side_effect = _provider_error()
        with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
            r = await client.post("/api/chat/", json={"question": "hi", "birth_data": _BIRTH})
        assert r.status_code == 503
        assert "busy" in r.json()["detail"]
        assert "org_01" not in r.text and "8000" not in r.text

    async def test_unexpected_error_is_a_generic_500(self):
        orch = MagicMock()
        orch.run.side_effect = RuntimeError(_SECRET)
        app.dependency_overrides[require_api_key] = lambda: None
        try:
            # The app's catch-all handler answers 500; keep the test client from re-raising the error afterwards.
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test", timeout=30) as ac:
                with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
                    r = await ac.post("/api/chat/", json={"question": "hi"})
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 500
        assert "org_01" not in r.text


class TestChatStreamErrors:
    async def test_stream_error_event_is_generic(self, client):
        async def boom(**_kw):
            raise _provider_error()
            yield  # pragma: no cover  (makes this an async generator)

        orch = MagicMock()
        orch.run_chat_stream = boom
        with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
            r = await client.post("/api/chat/stream", json={"question": "hi", "birth_data": _BIRTH})
        assert r.status_code == 200
        events = [json.loads(l[5:]) for l in r.text.splitlines() if l.startswith("data:")]
        err = next(e for e in events if e["type"] == "error")
        assert "org_01" not in err["message"]
        assert "busy" in err["message"]
