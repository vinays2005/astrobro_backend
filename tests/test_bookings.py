"""Pandit and puja bookings: catalogue, paying, cancelling, refunds and the admin's workflow."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database.connection import session_scope
from app.database.models import utcnow
from app.main import app
from app.security.auth import require_api_key
from app.services import wallet
from tests.firebase_helpers import bearer, install_verifier

OWNER_EMAIL = "owner@example.com"
OWNER = bearer("owner-1", email=OWNER_EMAIL)
SECRET = "booking_secret"


@pytest.fixture
async def api(monkeypatch):
    install_verifier()
    s = get_settings()
    monkeypatch.setattr(s, "admin_emails", [OWNER_EMAIL])
    monkeypatch.setattr(s, "razorpay_key_id", "rzp_test_abc")
    monkeypatch.setattr(s, "razorpay_key_secret", SECRET)
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60) as ac:
        yield ac
    app.dependency_overrides.clear()


async def fake_order(payload, transport=None):
    return {"id": "order_" + uuid.uuid4().hex[:14], "amount": payload["amount"]}


def when(hours: float = 48) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def make_service(api, price=250_000, active=True, slug=None) -> str:
    slug = slug or "puja-" + uuid.uuid4().hex[:8]
    r = await api.put("/api/admin/services", headers=OWNER, json={
        "id": slug, "name": "Griha Pravesh Puja", "description": "House-warming ceremony", "category": "puja",
        "price_paise": price, "duration_minutes": 120, "active": active})
    assert r.status_code == 200
    return slug


def request(service_id, **overrides) -> dict:
    return {"service_id": service_id, "scheduled_for": when(), "location_text": "Flat 4, Andheri, Mumbai",
            "notes": "North-east entrance", "contact_name": "Ravi Kumar", "contact_phone": "+91 98765 43210", **overrides}


async def book(api, who, service_id, **overrides):
    with patch("app.services.billing.create_razorpay_order", new=fake_order):
        return await api.post("/api/bookings", json=request(service_id, **overrides), headers=bearer(who))


async def pay(api, who, order_id):
    pid = "pay_" + uuid.uuid4().hex[:10]
    sig = hmac.new(SECRET.encode(), f"{order_id}|{pid}".encode(), hashlib.sha256).hexdigest()
    return await api.post("/api/billing/verify", headers=bearer(who), json={
        "razorpay_order_id": order_id, "razorpay_payment_id": pid, "razorpay_signature": sig})


def new_uid() -> str:
    return "u-" + uuid.uuid4().hex[:12]


class TestCatalogue:
    async def test_only_active_services_are_public_and_the_admin_sees_all(self, api):
        live, hidden = await make_service(api), await make_service(api, active=False)
        public = {s["id"] for s in (await api.get("/api/services")).json()["services"]}
        assert live in public and hidden not in public
        everything = {s["id"] for s in (await api.get("/api/admin/services", headers=OWNER)).json()["services"]}
        assert {live, hidden} <= everything

    async def test_updating_a_service(self, api):
        slug = await make_service(api, price=100_000)
        r = await api.put("/api/admin/services", headers=OWNER, json={
            "id": slug, "name": "Renamed", "price_paise": 120_000, "duration_minutes": 90, "active": True})
        assert r.json()["name"] == "Renamed" and r.json()["price_paise"] == 120_000

    async def test_only_the_owner_manages_services(self, api):
        payload = {"id": "sneaky", "name": "Free puja", "price_paise": 100}
        assert (await api.put("/api/admin/services", json=payload, headers=bearer(new_uid()))).status_code == 403
        assert (await api.put("/api/admin/services", json={"id": "Bad Slug!", "name": "x", "price_paise": 100}, headers=OWNER)).status_code == 422


class TestBooking:
    async def test_a_booking_is_created_unpaid_with_the_server_price(self, api):
        slug, who = await make_service(api, price=250_000), new_uid()
        r = await book(api, who, slug)
        assert r.status_code == 200
        body = r.json()
        assert body["booking"]["status"] == "pending_payment" and body["booking"]["price_paise"] == 250_000
        assert body["order"]["amount"] == 250_000 and body["order"]["purpose"] == "booking"
        assert (await api.get("/api/bookings", headers=bearer(who))).json()["bookings"][0]["id"] == body["booking"]["id"]

    async def test_paying_marks_it_paid(self, api):
        slug, who = await make_service(api), new_uid()
        body = (await book(api, who, slug)).json()
        assert (await pay(api, who, body["order"]["order_id"])).json()["purpose"] == "booking"
        mine = (await api.get("/api/bookings", headers=bearer(who))).json()["bookings"]
        assert mine[0]["status"] == "paid"

    async def test_validation(self, api):
        slug, who = await make_service(api), new_uid()
        assert (await book(api, who, slug, scheduled_for=when(1))).json()["detail"]["error"] == "too_soon"
        assert (await book(api, who, slug, scheduled_for=when(24 * 200))).json()["detail"]["error"] == "too_far"
        assert (await book(api, who, slug, contact_phone="12345abcde")).json()["detail"]["error"] == "bad_phone"
        assert (await book(api, who, "no-such-service")).status_code == 404
        hidden = await make_service(api, active=False)
        assert (await book(api, who, hidden)).status_code == 404
        r = await api.post("/api/bookings", json=request(slug), headers={})
        assert r.status_code == 401

    async def test_a_time_without_a_zone_means_india_time(self, api):
        slug, who = await make_service(api), new_uid()
        ist_tomorrow = (datetime.now(timezone.utc) + timedelta(hours=30)).astimezone(timezone(timedelta(hours=5, minutes=30)))
        naive = ist_tomorrow.replace(tzinfo=None).isoformat()
        r = await book(api, who, slug, scheduled_for=naive)
        stored = datetime.fromisoformat(r.json()["booking"]["scheduled_for"].rstrip("Z"))
        assert abs((stored - (utcnow() + timedelta(hours=30))).total_seconds()) < 120       # 30 hours from now, as UTC

    async def test_users_only_see_their_own_bookings(self, api):
        slug, a, b = await make_service(api), new_uid(), new_uid()
        await book(api, a, slug)
        assert (await api.get("/api/bookings", headers=bearer(b))).json()["bookings"] == []


class TestCancelling:
    async def test_an_unpaid_booking_is_simply_cancelled(self, api):
        slug, who = await make_service(api), new_uid()
        bid = (await book(api, who, slug)).json()["booking"]["id"]
        assert (await api.post(f"/api/bookings/{bid}/cancel", headers=bearer(who))).json()["status"] == "cancelled"

    async def test_a_paid_booking_is_refunded_to_the_wallet_in_full(self, api):
        slug, who = await make_service(api, price=180_000), new_uid()
        body = (await book(api, who, slug)).json()
        await pay(api, who, body["order"]["order_id"])
        r = await api.post(f"/api/bookings/{body['booking']['id']}/cancel", headers=bearer(who))
        assert r.json()["status"] == "refunded"
        assert (await api.get("/api/wallet", headers=bearer(who))).json()["balance_paise"] == 180_000
        again = await api.post(f"/api/bookings/{body['booking']['id']}/cancel", headers=bearer(who))
        assert again.status_code == 409                                                  # cannot refund twice
        assert (await api.get("/api/wallet", headers=bearer(who))).json()["balance_paise"] == 180_000

    async def test_a_confirmed_booking_needs_the_owner(self, api):
        slug, who = await make_service(api), new_uid()
        body = (await book(api, who, slug)).json()
        await pay(api, who, body["order"]["order_id"])
        bid = body["booking"]["id"]
        await api.post(f"/api/admin/bookings/{bid}/status", json={"status": "confirmed", "assigned_uid": "pandit-1"}, headers=OWNER)
        r = await api.post(f"/api/bookings/{bid}/cancel", headers=bearer(who))
        assert r.status_code == 409 and r.json()["detail"]["error"] == "cannot_cancel"

    async def test_nobody_can_cancel_someone_elses_booking(self, api):
        slug, who = await make_service(api), new_uid()
        bid = (await book(api, who, slug)).json()["booking"]["id"]
        assert (await api.post(f"/api/bookings/{bid}/cancel", headers=bearer(new_uid()))).status_code == 404


class TestAdminWorkflow:
    async def paid_booking(self, api, price=100_000):
        slug, who = await make_service(api, price=price), new_uid()
        body = (await book(api, who, slug)).json()
        await pay(api, who, body["order"]["order_id"])
        return who, body["booking"]["id"]

    async def test_confirm_then_complete(self, api):
        who, bid = await self.paid_booking(api)
        listed = (await api.get("/api/admin/bookings?status=paid", headers=OWNER)).json()["bookings"]
        mine = next(b for b in listed if b["id"] == bid)
        assert mine["contact_phone"] == "+91 98765 43210" and mine["user_uid"] == who      # the owner sees contact details
        confirmed = (await api.post(f"/api/admin/bookings/{bid}/status", headers=OWNER,
                                    json={"status": "confirmed", "assigned_uid": "pandit-7", "note": "Pandit Sharma will call"})).json()
        assert confirmed["status"] == "confirmed" and confirmed["assigned_uid"] == "pandit-7"
        assert (await api.post(f"/api/admin/bookings/{bid}/status", json={"status": "completed"}, headers=OWNER)).json()["status"] == "completed"
        seen_by_user = (await api.get("/api/bookings", headers=bearer(who))).json()["bookings"][0]
        assert "contact_phone" not in seen_by_user and seen_by_user["admin_note"] == "Pandit Sharma will call"

    async def test_refund_after_the_fact_goes_to_the_wallet(self, api):
        who, bid = await self.paid_booking(api, price=75_000)
        r = await api.post(f"/api/admin/bookings/{bid}/status", json={"status": "refunded", "note": "Pandit unavailable"}, headers=OWNER)
        assert r.json()["status"] == "refunded"
        async with session_scope() as db:
            assert await wallet.balance(db, who) == 75_000

    async def test_impossible_moves_are_refused(self, api):
        who, bid = await self.paid_booking(api)
        for status in ("completed", "cancelled"):                                   # paid cannot jump straight there
            r = await api.post(f"/api/admin/bookings/{bid}/status", json={"status": status}, headers=OWNER)
            assert r.status_code == 409 and r.json()["detail"]["error"] == "bad_transition"
        assert (await api.post("/api/admin/bookings/missing/status", json={"status": "confirmed"}, headers=OWNER)).status_code == 404
        assert (await api.post(f"/api/admin/bookings/{bid}/status", json={"status": "teleported"}, headers=OWNER)).status_code == 422

    async def test_the_admin_sees_the_new_booking_in_the_summary(self, api):
        await self.paid_booking(api)
        stats = (await api.get("/api/admin/summary", headers=OWNER)).json()
        assert stats["bookings"]["paid"] >= 1 and stats["money_paise"]["booking_sales"] >= 100_000
