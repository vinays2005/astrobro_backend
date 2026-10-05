"""Billing: orders, verification, replay safety, ownership and the Razorpay webhook (Razorpay itself is faked)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database.connection import session_scope
from app.main import app
from app.security.auth import require_api_key
from app.services import accounts, wallet
from tests.firebase_helpers import bearer, install_verifier

SECRET = "test_key_secret"
WEBHOOK_SECRET = "test_webhook_secret"


@pytest.fixture
async def client(monkeypatch):
    install_verifier()
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc")
    monkeypatch.setattr(settings, "razorpay_key_secret", SECRET)
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def fake_create_razorpay_order(payload, transport=None):
    return {"id": "order_" + uuid.uuid4().hex[:14], "amount": payload["amount"]}


def sign(order_id: str, payment_id: str, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def new_uid() -> str:
    return "u-" + uuid.uuid4().hex[:12]


async def order(client, uid, **body):
    with patch("app.services.billing.create_razorpay_order", new=fake_create_razorpay_order):
        return await client.post("/api/billing/orders", json=body, headers=bearer(uid))


async def pay(client, uid, order_id, payment_id=None, signature=None):
    payment_id = payment_id or "pay_" + uuid.uuid4().hex[:12]
    return await client.post("/api/billing/verify", headers=bearer(uid), json={
        "razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
        "razorpay_signature": signature or sign(order_id, payment_id)})


class TestPlans:
    async def test_plans_endpoint_is_the_single_source_of_truth(self, client):
        body = (await client.get("/api/billing/plans")).json()
        assert {p["id"]: (p["price_paise"], p["days"]) for p in body["plans"]} == {
            "weekly": (4900, 7), "monthly": (14900, 30), "quarterly": (39900, 90), "yearly": (99900, 365)}
        assert body["report_price_paise"] == 4900 and body["report_free_for_premium"] is True
        assert body["wallet"]["min_topup_paise"] < body["wallet"]["max_topup_paise"]


class TestCreateOrder:
    @pytest.mark.parametrize("plan,paise", [("weekly", 4900), ("monthly", 14900), ("quarterly", 39900), ("yearly", 99900)])
    async def test_plan_orders_use_the_server_price(self, client, plan, paise):
        r = await order(client, new_uid(), purpose="plan", plan_id=plan, amount_paise=1)     # a client-sent amount is ignored
        assert r.status_code == 200
        body = r.json()
        assert body["amount"] == paise and body["currency"] == "INR" and body["order_id"].startswith("order_")
        assert body["key_id"] == "rzp_test_abc"

    async def test_report_order_uses_the_report_price(self, client):
        assert (await order(client, new_uid(), purpose="report")).json()["amount"] == get_settings().paid_report_price

    async def test_wallet_topup_amount_is_bounded(self, client):
        uid = new_uid()
        s = get_settings()
        assert (await order(client, uid, purpose="wallet", amount_paise=20000)).json()["amount"] == 20000
        assert (await order(client, uid, purpose="wallet")).status_code == 400
        assert (await order(client, uid, purpose="wallet", amount_paise=s.wallet_min_topup_paise - 1)).status_code == 400
        assert (await order(client, uid, purpose="wallet", amount_paise=s.wallet_max_topup_paise + 1)).status_code == 400

    async def test_unknown_plan_and_purpose_are_rejected(self, client):
        assert (await order(client, new_uid(), purpose="plan", plan_id="lifetime")).status_code == 400
        assert (await order(client, new_uid(), purpose="plan")).status_code == 400
        assert (await order(client, new_uid(), purpose="booking")).status_code == 422      # bookings use their own endpoint

    async def test_signing_in_is_required(self, client):
        r = await client.post("/api/billing/orders", json={"purpose": "plan", "plan_id": "weekly"})
        assert r.status_code == 401

    async def test_blocked_accounts_cannot_start_a_payment(self, client):
        from app.database.models import Account

        uid = new_uid()
        assert (await order(client, uid, purpose="report")).status_code == 200
        async with session_scope() as db:
            (await db.get(Account, uid)).is_blocked = True
        assert (await order(client, uid, purpose="report")).status_code == 403

    async def test_payments_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_key_secret", "")
        r = await client.post("/api/billing/orders", json={"purpose": "report"}, headers=bearer(new_uid()))
        assert r.status_code == 503

    async def test_razorpay_failure_is_a_clean_502(self, client):
        async def broken(payload, transport=None):
            raise RuntimeError("secret internals key=abc")

        with patch("app.services.billing.create_razorpay_order", new=broken):
            r = await client.post("/api/billing/orders", json={"purpose": "report"}, headers=bearer(new_uid()))
        assert r.status_code == 502 and "abc" not in r.text


class TestRazorpayRestCall:
    async def test_sends_the_order_the_way_razorpay_expects(self, monkeypatch):
        from app.services import billing

        monkeypatch.setattr(get_settings(), "razorpay_key_id", "rzp_test_abc")
        monkeypatch.setattr(get_settings(), "razorpay_key_secret", SECRET)
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "order_x", "amount": seen["body"]["amount"]})

        order = await billing.create_razorpay_order({"amount": 4900, "currency": "INR"}, transport=httpx.MockTransport(handler))
        assert order["id"] == "order_x"
        assert seen["url"] == "https://api.razorpay.com/v1/orders"
        assert seen["auth"] == "Basic " + base64.b64encode(f"rzp_test_abc:{SECRET}".encode()).decode()
        assert seen["body"] == {"amount": 4900, "currency": "INR"}

    async def test_a_rejection_from_razorpay_becomes_a_502(self, monkeypatch):
        from app.services import billing

        monkeypatch.setattr(get_settings(), "razorpay_key_id", "rzp_test_abc")
        monkeypatch.setattr(get_settings(), "razorpay_key_secret", SECRET)
        transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": {"description": "bad"}}))
        with pytest.raises(billing.BillingError) as err:
            await billing.create_razorpay_order({"amount": 1}, transport=transport)
        assert err.value.status == 502

    async def test_not_configured_is_a_503_and_makes_no_request(self, monkeypatch):
        from app.services import billing

        monkeypatch.setattr(get_settings(), "razorpay_key_secret", "")
        transport = httpx.MockTransport(lambda request: pytest.fail("no request should be sent"))
        with pytest.raises(billing.BillingError) as err:
            await billing.create_razorpay_order({"amount": 1}, transport=transport)
        assert err.value.status == 503


class TestVerify:
    async def test_paying_for_a_plan_grants_premium_on_the_server(self, client):
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        assert (await client.get("/api/me", headers=bearer(uid))).json()["plan"] == "free"
        r = await pay(client, uid, o["order_id"])
        assert r.status_code == 200 and r.json()["success"] is True and r.json()["premium_until"]
        me = (await client.get("/api/me", headers=bearer(uid))).json()
        assert me["plan"] == "premium" and me["chat_limit"] == get_settings().premium_chats_per_day

    async def test_verifying_twice_does_not_double_grant(self, client):
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        first = (await pay(client, uid, o["order_id"], "pay_same")).json()["premium_until"]
        second = (await pay(client, uid, o["order_id"], "pay_same")).json()["premium_until"]
        assert first == second

    async def test_a_second_payment_extends_premium(self, client):
        uid = new_uid()
        a = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        first = (await pay(client, uid, a["order_id"])).json()["premium_until"]
        b = (await order(client, uid, purpose="plan", plan_id="monthly")).json()
        second = (await pay(client, uid, b["order_id"])).json()["premium_until"]
        assert second > first

    async def test_wallet_topup_is_credited_exactly_once(self, client):
        uid = new_uid()
        o = (await order(client, uid, purpose="wallet", amount_paise=25000)).json()
        await pay(client, uid, o["order_id"], "pay_w1")
        r = await pay(client, uid, o["order_id"], "pay_w1")
        assert r.json()["wallet_balance_paise"] == 25000
        assert (await client.get("/api/wallet", headers=bearer(uid))).json()["balance_paise"] == 25000

    async def test_wrong_signature_is_refused_and_grants_nothing(self, client):
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        r = await pay(client, uid, o["order_id"], signature="0" * 64)
        assert r.status_code == 400
        assert (await client.get("/api/me", headers=bearer(uid))).json()["plan"] == "free"

    async def test_signature_for_a_different_payment_id_is_refused(self, client):
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        r = await pay(client, uid, o["order_id"], "pay_real", sign(o["order_id"], "pay_other"))
        assert r.status_code == 400

    async def test_someone_elses_order_cannot_be_claimed(self, client):
        owner, thief = new_uid(), new_uid()
        o = (await order(client, owner, purpose="plan", plan_id="weekly")).json()
        r = await pay(client, thief, o["order_id"])
        assert r.status_code == 403
        assert (await client.get("/api/me", headers=bearer(thief))).json()["plan"] == "free"

    async def test_unknown_order_and_missing_login(self, client):
        assert (await pay(client, new_uid(), "order_doesnotexist")).status_code == 404
        r = await client.post("/api/billing/verify", json={
            "razorpay_order_id": "o", "razorpay_payment_id": "p", "razorpay_signature": "s"})
        assert r.status_code == 401

    async def test_one_payment_id_cannot_settle_two_orders(self, client):
        uid = new_uid()
        a = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        b = (await order(client, uid, purpose="plan", plan_id="weekly")).json()
        assert (await pay(client, uid, a["order_id"], "pay_reused")).status_code == 200
        assert (await pay(client, uid, b["order_id"], "pay_reused")).status_code == 409


class TestWebhook:
    def body(self, order_id, payment_id, amount, event="payment.captured") -> bytes:
        return json.dumps({"event": event, "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount}}}}).encode()

    async def post(self, client, raw: bytes, secret: str = WEBHOOK_SECRET):
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return await client.post("/api/billing/webhook", content=raw,
                                 headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"})

    async def test_off_until_a_secret_is_configured(self, client):
        assert (await client.post("/api/billing/webhook", content=b"{}")).status_code == 404

    async def test_bad_signature_is_refused(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", WEBHOOK_SECRET)
        r = await self.post(client, self.body("o", "p", 100), secret="wrong")
        assert r.status_code == 400

    async def test_a_captured_payment_settles_even_if_the_app_never_called_verify(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", WEBHOOK_SECRET)
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="monthly")).json()
        raw = self.body(o["order_id"], "pay_hook1", o["amount"])
        assert (await self.post(client, raw)).status_code == 200
        assert (await self.post(client, raw)).status_code == 200                     # Razorpay retries: harmless
        me = (await client.get("/api/me", headers=bearer(uid))).json()
        assert me["plan"] == "premium"
        async with session_scope() as db:
            assert await accounts.is_premium(db, uid)

    async def test_a_wrong_amount_does_not_settle(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", WEBHOOK_SECRET)
        uid = new_uid()
        o = (await order(client, uid, purpose="plan", plan_id="monthly")).json()
        assert (await self.post(client, self.body(o["order_id"], "pay_hook2", 100))).status_code == 200
        assert (await client.get("/api/me", headers=bearer(uid))).json()["plan"] == "free"

    async def test_unknown_orders_and_other_events_are_acknowledged(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", WEBHOOK_SECRET)
        assert (await self.post(client, self.body("order_unknown", "pay_x", 100))).status_code == 200
        assert (await self.post(client, self.body("o", "p", 1, event="refund.created"))).status_code == 200
        assert (await self.post(client, b"not json")).status_code == 200

    async def test_wallet_topup_through_the_webhook(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", WEBHOOK_SECRET)
        uid = new_uid()
        o = (await order(client, uid, purpose="wallet", amount_paise=15000)).json()
        await self.post(client, self.body(o["order_id"], "pay_hook3", 15000))
        await pay(client, uid, o["order_id"], "pay_hook3")                         # the app verifies later: still one credit
        async with session_scope() as db:
            assert await wallet.balance(db, uid) == 15000
