"""The API must start, and keep serving calculated features, even when the AI layer cannot come up."""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import app.agents.singleton as singleton
import app.api.routes_health as health_module
import app.main as main
from app.main import app
from app.security.auth import require_api_key

BIRTH = {"name": "Arjun", "date_of_birth": "1990-08-15", "time_of_birth": "14:30", "timezone": "Asia/Kolkata",
         "latitude": 19.076, "longitude": 72.8777}


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=120) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    saved = singleton._orchestrator
    # Health probes talk to Groq and Qdrant: keep the tests offline and start each one with a cold cache.
    monkeypatch.setattr(health_module, "_probe_upstreams", lambda: (False, 0))
    monkeypatch.setitem(health_module._cache, "at", float("-inf"))
    yield
    singleton.set_orchestrator(saved)


class TestAiUnavailable:
    def test_get_orchestrator_raises_a_typed_error(self):
        singleton.set_orchestrator(None)
        assert singleton.is_ready() is False
        with pytest.raises(singleton.AIUnavailableError):
            singleton.get_orchestrator()

    @pytest.mark.parametrize("path,body", [
        ("/api/chat/", {"question": "hi"}),
        ("/api/chat/stream", {"question": "hi"}),
        ("/api/prediction/", {"birth_data": BIRTH, "topic": "career"}),
        ("/api/kundli/predict", {"birth_data": BIRTH, "topic": "career"}),
    ])
    async def test_ai_routes_answer_503_without_internal_details(self, client, path, body):
        singleton.set_orchestrator(None)
        r = await client.post(path, json=body)
        assert r.status_code == 503
        assert r.json()["error"] == "ai_unavailable"
        assert "GROQ" not in r.text and "Traceback" not in r.text

    async def test_calculated_features_do_not_need_the_ai_layer(self, client):
        singleton.set_orchestrator(None)
        for url in ("/api/features", "/api/tarot/spreads", "/api/horoscope/Aries?period=daily&date=2026-10-05",
                    "/api/panchang?date=2026-10-20&latitude=19.07&longitude=72.87&timezone=Asia/Kolkata"):
            assert (await client.get(url)).status_code == 200, url
        r = await client.post("/api/numerology/profile", json={"name": "Arjun Sharma", "date_of_birth": "1990-08-15"})
        assert r.status_code == 200


class TestHealth:
    async def test_reports_ai_readiness_live_and_caches_the_upstream_probes(self, client, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(health_module, "_probe_upstreams", lambda: (calls.append(1), (True, 123))[1])

        singleton.set_orchestrator(None)
        first = (await client.get("/api/health")).json()
        assert first["status"] == "ok" and first["ai_ready"] is False
        assert first["llm_connected"] is True and first["vector_db_chunks"] == 123

        singleton.set_orchestrator(object())
        second = (await client.get("/api/health")).json()
        assert second["ai_ready"] is True
        assert len(calls) == 1        # readiness is live; the network probes are reused for a while

    async def test_health_stays_ok_when_nothing_is_configured(self, client):
        singleton.set_orchestrator(None)
        r = await client.get("/api/health")
        assert r.status_code == 200 and r.json()["llm_connected"] is False


class TestStartup:
    async def test_app_starts_when_the_ai_layer_fails_and_recovers_in_the_background(self, monkeypatch):
        singleton.set_orchestrator(None)
        monkeypatch.setattr(main, "_ORCHESTRATOR_RETRY_SECONDS", 0.01)
        attempts: list[int] = []

        class Flaky:
            def __init__(self) -> None:
                attempts.append(1)
                if len(attempts) < 3:
                    raise ValueError("GROQ_API_KEY not set")

        monkeypatch.setattr("app.agents.orchestrator.AgentOrchestrator", Flaky)
        async with app.router.lifespan_context(app):
            assert singleton.is_ready() is False and len(attempts) == 1      # start-up did not crash
            for _ in range(200):
                if singleton.is_ready():
                    break
                await asyncio.sleep(0.05)
            assert singleton.is_ready() and len(attempts) == 3

    async def test_retries_stop_at_shutdown(self, monkeypatch):
        singleton.set_orchestrator(None)
        monkeypatch.setattr(main, "_ORCHESTRATOR_RETRY_SECONDS", 0.01)
        attempts: list[int] = []

        class Broken:
            def __init__(self) -> None:
                attempts.append(1)
                raise ConnectionError("vector db unreachable")

        monkeypatch.setattr("app.agents.orchestrator.AgentOrchestrator", Broken)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.2)
            assert singleton.is_ready() is False and len(attempts) >= 2
        count = len(attempts)
        await asyncio.sleep(0.2)
        assert len(attempts) == count
