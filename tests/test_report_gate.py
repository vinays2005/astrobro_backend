"""The paid PDF report: included with premium, otherwise one paid order buys one report, and failures hand it back."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database.connection import session_scope
from app.main import app
from app.security.auth import require_api_key
from app.services import accounts
from tests.firebase_helpers import bearer, install_verifier

SECRET = "report_secret"
BODY = {"name": "Arjun", "date_of_birth": "1990-08-15", "time_of_birth": "14:30", "latitude": 19.076,
        "longitude": 72.8777, "timezone": 5.5, "tier": "paid"}


@pytest.fixture
async def client(monkeypatch):
    install_verifier()
    s = get_settings()
    monkeypatch.setattr(s, "razorpay_key_id", "rzp_test_abc")
    monkeypatch.setattr(s, "razorpay_key_secret", SECRET)
    monkeypatch.setattr(s, "auto_approve_payments", False)
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60) as ac:
        yield ac
    app.dependency_overrides.clear()


def uid() -> str:
    return "u-" + uuid.uuid4().hex[:12]


async def fake_render(body):
    return Response(content=b"%PDF-fake", media_type="application/pdf")


async def buy_report(client, who) -> str:
    """Create and verify a report order the way the app does; returns the order id."""
    async def fake_order(payload, transport=None):
        return {"id": "order_" + uuid.uuid4().hex[:14], "amount": payload["amount"]}

    with patch("app.services.billing.create_razorpay_order", new=fake_order):
        o = (await client.post("/api/billing/orders", json={"purpose": "report"}, headers=bearer(who))).json()
    pid = "pay_" + uuid.uuid4().hex[:10]
    sig = hmac.new(SECRET.encode(), f"{o['order_id']}|{pid}".encode(), hashlib.sha256).hexdigest()
    r = await client.post("/api/billing/verify", headers=bearer(who), json={
        "razorpay_order_id": o["order_id"], "razorpay_payment_id": pid, "razorpay_signature": sig})
    assert r.status_code == 200
    return o["order_id"]


async def generate(client, who=None, render=fake_render, **extra):
    with patch("app.api.routes_report._render_report", new=render):
        return await client.post("/api/report/generate", json={**BODY, **extra}, headers=bearer(who) if who else {})


class TestPaidReport:
    async def test_the_free_report_needs_nothing(self, client):
        assert (await generate(client, tier="free")).status_code == 200

    async def test_anonymous_callers_cannot_get_the_paid_report(self, client):
        r = await generate(client)
        assert r.status_code == 402 and "sign in" in r.json()["detail"].lower()

    async def test_signed_in_users_without_a_purchase_are_asked_to_pay(self, client):
        r = await generate(client, uid())
        assert r.status_code == 402 and r.json()["detail"] == "Payment required"

    async def test_premium_includes_the_report(self, client):
        who = uid()
        async with session_scope() as db:
            await accounts.grant_premium(db, who, 7)
        assert (await generate(client, who)).status_code == 200
        assert (await generate(client, who)).status_code == 200          # as many as they like

    async def test_premium_can_be_made_a_paid_extra(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "report_free_for_premium", False)
        who = uid()
        async with session_scope() as db:
            await accounts.grant_premium(db, who, 7)
        assert (await generate(client, who)).status_code == 402

    async def test_one_paid_order_buys_exactly_one_report(self, client):
        who = uid()
        order_id = await buy_report(client, who)
        assert (await generate(client, who, razorpay_order_id=order_id)).status_code == 200
        again = await generate(client, who, razorpay_order_id=order_id)
        assert again.status_code == 402                                   # the replay that used to be possible

    async def test_a_payment_signature_alone_is_no_longer_enough(self, client):
        who = uid()
        sig = hmac.new(SECRET.encode(), b"order_1|pay_1", hashlib.sha256).hexdigest()
        r = await generate(client, who, razorpay_order_id="order_1", razorpay_payment_id="pay_1", razorpay_signature=sig)
        assert r.status_code == 402

    async def test_someone_elses_paid_order_cannot_be_used(self, client):
        buyer, thief = uid(), uid()
        order_id = await buy_report(client, buyer)
        assert (await generate(client, thief, razorpay_order_id=order_id)).status_code == 402
        assert (await generate(client, buyer, razorpay_order_id=order_id)).status_code == 200

    async def test_a_plan_order_is_not_a_report_order(self, client):
        who = uid()

        async def fake_order(payload, transport=None):
            return {"id": "order_" + uuid.uuid4().hex[:14], "amount": payload["amount"]}

        with patch("app.services.billing.create_razorpay_order", new=fake_order):
            o = (await client.post("/api/billing/orders", json={"purpose": "wallet", "amount_paise": 20000},
                                   headers=bearer(who))).json()
        pid = "pay_" + uuid.uuid4().hex[:10]
        sig = hmac.new(SECRET.encode(), f"{o['order_id']}|{pid}".encode(), hashlib.sha256).hexdigest()
        await client.post("/api/billing/verify", headers=bearer(who), json={
            "razorpay_order_id": o["order_id"], "razorpay_payment_id": pid, "razorpay_signature": sig})
        assert (await generate(client, who, razorpay_order_id=o["order_id"])).status_code == 402

    async def test_a_failed_report_hands_the_purchase_back(self, client):
        who = uid()
        order_id = await buy_report(client, who)

        async def broken(body):
            raise HTTPException(status_code=500, detail="PDF generation failed")

        assert (await generate(client, who, render=broken, razorpay_order_id=order_id)).status_code == 500
        assert (await generate(client, who, razorpay_order_id=order_id)).status_code == 200      # still theirs

    async def test_development_mode_skips_the_check(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "auto_approve_payments", True)
        assert (await generate(client)).status_code == 200
