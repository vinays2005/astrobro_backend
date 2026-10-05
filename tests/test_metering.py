"""Server-side chat limits: counted per signed-in user, given back on failure, rate-limited without a login."""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import httpx
import pytest
from groq import APIStatusError
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database.connection import session_scope
from app.main import app
from app.security.auth import require_api_key
from app.services import accounts, metering
from tests.firebase_helpers import bearer, install_verifier


class FakeOrchestrator:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def run(self, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return {"request_id": "r", "answer": "ok", "errors": []}

    async def run_chat_stream(self, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        yield "ok"


def provider_error() -> APIStatusError:
    req = httpx.Request("POST", "https://api.groq.com/x")
    return APIStatusError("org_01 limit", response=httpx.Response(429, request=req), body=None)


@pytest.fixture
async def client(monkeypatch):
    install_verifier()
    monkeypatch.setattr(get_settings(), "free_chats_per_day", 3)
    monkeypatch.setattr(get_settings(), "premium_chats_per_day", 6)
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30) as ac:
        yield ac
    app.dependency_overrides.clear()


def uid() -> str:
    return "u-" + uuid.uuid4().hex[:12]


async def chat(client, who, orch, path="/api/chat/", **headers):
    body = {"question": "hi"}
    h = bearer(who) if who else {}
    h.update(headers)
    with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
        return await client.post(path, json=body, headers=h)


async def used(who) -> int:
    async with session_scope() as db:
        return await accounts.usage_today(db, who)


class TestPerUserLimit:
    async def test_the_free_limit_is_enforced_by_the_server(self, client):
        who, orch = uid(), FakeOrchestrator()
        codes = [(await chat(client, who, orch)).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        assert orch.calls == 3                                       # the AI was never called once the limit was hit

    async def test_the_limit_error_tells_the_app_what_to_show(self, client):
        who, orch = uid(), FakeOrchestrator()
        for _ in range(3):
            await chat(client, who, orch)
        detail = (await chat(client, who, orch)).json()["detail"]
        assert detail["error"] == "limit_reached" and detail["used"] == 3 and detail["limit"] == 3
        assert detail["premium"] is False and "upgrade" in detail["message"].lower()

    async def test_users_do_not_share_allowances(self, client):
        a, b, orch = uid(), uid(), FakeOrchestrator()
        for _ in range(3):
            await chat(client, a, orch)
        assert (await chat(client, a, orch)).status_code == 429
        assert (await chat(client, b, orch)).status_code == 200

    async def test_premium_users_get_the_higher_cap_and_a_different_message(self, client):
        who, orch = uid(), FakeOrchestrator()
        async with session_scope() as db:
            await accounts.grant_premium(db, who, 7)
        codes = [(await chat(client, who, orch)).status_code for _ in range(7)]
        assert codes == [200] * 6 + [429]
        detail = (await chat(client, who, orch)).json()["detail"]
        assert detail["premium"] is True and "upgrade" not in detail["message"].lower()

    async def test_the_stream_route_is_limited_too(self, client):
        who, orch = uid(), FakeOrchestrator()
        codes = [(await chat(client, who, orch, "/api/chat/stream")).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]

    async def test_suspended_accounts_are_refused(self, client):
        from app.database.models import Account

        who, orch = uid(), FakeOrchestrator()
        assert (await chat(client, who, orch)).status_code == 200
        async with session_scope() as db:
            (await db.get(Account, who)).is_blocked = True
        r = await chat(client, who, orch)
        assert r.status_code == 403 and "suspended" in r.json()["detail"]

    async def test_me_reports_the_server_side_count(self, client):
        who, orch = uid(), FakeOrchestrator()
        await chat(client, who, orch)
        await chat(client, who, orch)
        me = (await client.get("/api/me", headers=bearer(who))).json()
        assert (me["chats_used_today"], me["chat_limit"], me["chats_remaining"]) == (2, 3, 1)


class TestFailuresAreGivenBack:
    async def test_a_provider_error_does_not_cost_a_chat(self, client):
        who = uid()
        r = await chat(client, who, FakeOrchestrator(provider_error()))
        assert r.status_code == 503 and "org_01" not in r.text
        assert await used(who) == 0

    async def test_an_unexpected_error_does_not_cost_a_chat_either(self, client):
        who = uid()
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.api.routes_chat.get_orchestrator", return_value=FakeOrchestrator(RuntimeError("boom"))):
                r = await ac.post("/api/chat/", json={"question": "hi"}, headers=bearer(who))
        assert r.status_code == 500
        assert await used(who) == 0

    async def test_a_failed_stream_gives_the_chat_back(self, client):
        who = uid()
        r = await chat(client, who, FakeOrchestrator(provider_error()), "/api/chat/stream")
        events = [json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")]
        assert any(e["type"] == "error" for e in events)
        assert await used(who) == 0

    async def test_ai_being_unavailable_does_not_count(self, client):
        from app.agents.singleton import AIUnavailableError

        who = uid()
        with patch("app.api.routes_chat.get_orchestrator", side_effect=AIUnavailableError("down")):
            assert (await client.post("/api/chat/", json={"question": "hi"}, headers=bearer(who))).status_code == 503
        assert await used(who) == 0


class TestWithoutALogin:
    """Older app versions send only the API key. They keep working, with a per-address limit."""

    async def test_requests_without_a_token_still_work(self, client):
        assert (await chat(client, None, FakeOrchestrator())).status_code == 200

    async def test_each_address_gets_its_own_hourly_limit(self, client, monkeypatch):
        monkeypatch.setattr(metering, "ANON_CHATS_PER_HOUR", 2)
        orch = FakeOrchestrator()
        a = {"X-Forwarded-For": "203.0.113.5"}
        codes = [(await chat(client, None, orch, **a)).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        assert (await chat(client, None, orch, **{"X-Forwarded-For": "203.0.113.6"})).status_code == 200
        assert (await chat(client, None, orch, **a)).json()["detail"]["error"] == "slow_down"

    async def test_a_forged_forwarded_for_prefix_does_not_dodge_the_limit(self, client, monkeypatch):
        monkeypatch.setattr(metering, "ANON_CHATS_PER_HOUR", 1)
        orch = FakeOrchestrator()
        assert (await chat(client, None, orch, **{"X-Forwarded-For": "1.1.1.1, 198.51.100.9"})).status_code == 200
        r = await chat(client, None, orch, **{"X-Forwarded-For": "2.2.2.2, 198.51.100.9"})      # only the proxy-added part counts
        assert r.status_code == 429

    async def test_strict_mode_requires_a_token(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "require_id_token", True)
        assert (await chat(client, None, FakeOrchestrator())).status_code == 401
        assert (await chat(client, uid(), FakeOrchestrator())).status_code == 200


class TestClientAddress:
    def test_private_proxy_hops_are_skipped(self):
        from starlette.requests import Request

        from app.security.ratelimit import client_ip

        def req(xff, peer=("100.64.0.9", 1)):
            return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())] if xff else [], "client": peer})

        assert client_ip(req("9.9.9.9, 100.64.0.2")) == "9.9.9.9"
        assert client_ip(req("")) == "100.64.0.9"
        assert client_ip(req("garbage")) == "100.64.0.9"
        assert client_ip(req("10.0.0.1, 192.168.1.1")) == "100.64.0.9"
