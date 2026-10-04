"""Payment route tests — Razorpay is mocked, no real keys needed."""
from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.api.routes_payment import PLAN_PRICES
from app.main import app
from app.security.auth import require_api_key


async def _no_auth() -> None:
    return


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = _no_auth
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


def _fake_razorpay():
    fake = MagicMock()
    fake.order.create.side_effect = lambda payload: {
        "id": "order_test123",
        "amount": payload["amount"],
    }
    return fake


class TestPlanPrices:
    def test_prices_match_app_paywall(self):
        # Must stay in sync with _plans in lib/screens/paywall/paywall_screen.dart
        assert PLAN_PRICES == {
            "weekly": 4900,
            "monthly": 14900,
            "quarterly": 39900,
            "yearly": 99900,
        }


class TestCreateOrder:
    @pytest.mark.parametrize("plan_id,paise", [
        ("weekly", 4900),
        ("monthly", 14900),
        ("quarterly", 39900),
        ("yearly", 99900),
    ])
    async def test_creates_order_with_correct_amount(self, client, plan_id, paise):
        settings = SimpleNamespace(razorpay_key_id="rzp_test_x", razorpay_key_secret="s")
        with patch("app.api.routes_payment._razorpay_client", return_value=_fake_razorpay()), \
             patch("app.api.routes_payment.get_settings", return_value=settings):
            r = await client.post(
                "/api/payment/create-order",
                json={"plan_id": plan_id, "user_id": "user123"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["amount"] == paise
        assert body["currency"] == "INR"
        assert body["order_id"] == "order_test123"

    async def test_unknown_plan_rejected(self, client):
        r = await client.post(
            "/api/payment/create-order",
            json={"plan_id": "lifetime", "user_id": "user123"},
        )
        assert r.status_code == 400


class TestVerify:
    _SECRET = "test_secret"

    def _body(self, signature: str) -> dict:
        return {
            "razorpay_payment_id": "pay_1",
            "razorpay_order_id": "order_1",
            "razorpay_signature": signature,
            "user_id": "user123",
            "plan_id": "weekly",
        }

    async def test_valid_signature_accepted(self, client):
        sig = hmac.new(self._SECRET.encode(), b"order_1|pay_1", hashlib.sha256).hexdigest()
        settings = SimpleNamespace(razorpay_key_secret=self._SECRET)
        with patch("app.api.routes_payment.get_settings", return_value=settings):
            r = await client.post("/api/payment/verify", json=self._body(sig))
        assert r.status_code == 200
        assert r.json() == {"success": True}

    async def test_invalid_signature_rejected(self, client):
        settings = SimpleNamespace(razorpay_key_secret=self._SECRET)
        with patch("app.api.routes_payment.get_settings", return_value=settings):
            r = await client.post("/api/payment/verify", json=self._body("bad"))
        assert r.status_code == 400
