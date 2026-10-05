"""The marketplace over HTTP: one full story from application to payout, plus permissions and error shapes."""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes_consult
from app.config import get_settings
from app.main import app
from app.security.auth import require_api_key
from tests.firebase_helpers import bearer, install_verifier

OWNER_EMAIL = "owner@example.com"


@pytest.fixture
async def api(monkeypatch):
    install_verifier()
    monkeypatch.setattr(get_settings(), "admin_emails", [OWNER_EMAIL])
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60) as ac:
        yield ac
    app.dependency_overrides.clear()


def uid(prefix="u") -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


OWNER = bearer("owner-1", email=OWNER_EMAIL)
PROFILE = {"name": "Acharya Rao", "bio": "Vedic astrology for 15 years", "languages": ["Hindi", "English"],
           "specialties": ["Marriage", "Career"], "experience_years": 15, "chat_rate_paise": 1000, "call_rate_paise": 2000,
           "payout_upi": "acharya@okbank"}


async def make_approved_online_astrologer(api, name="Acharya Rao", **overrides) -> tuple[str, dict]:
    who = uid("astro")
    h = bearer(who, email=f"{who}@example.com")
    r = await api.post("/api/astrologer/apply", json={**PROFILE, "name": name, **overrides}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert (await api.post(f"/api/admin/astrologers/{who}/approve", headers=OWNER)).status_code == 200
    assert (await api.post("/api/astrologer/presence", json={"online": True}, headers=h)).json()["online"] is True
    return who, h


async def make_funded_user(api, rupees=200) -> tuple[str, dict]:
    who = uid()
    h = bearer(who, email=f"{who}@example.com")
    assert (await api.post("/api/me/accept-terms", headers=h)).json()["terms_accepted"] is True
    r = await api.post("/api/admin/wallet/adjust", json={"uid": who, "amount_paise": rupees * 100, "note": "test top-up"},
                       headers=OWNER)
    assert r.json()["balance_paise"] == rupees * 100
    return who, h


class TestTheWholeStory:
    async def test_from_application_to_payout(self, api):
        # 1. an astrologer applies; nobody sees them until the owner approves
        astro_uid = uid("astro")
        astro = bearer(astro_uid, email=f"{astro_uid}@example.com")
        assert (await api.post("/api/astrologer/apply", json=PROFILE, headers=astro)).json()["status"] == "pending"
        assert all(i["uid"] != astro_uid for i in (await api.get("/api/astrologers?limit=50")).json()["items"])
        assert (await api.get(f"/api/astrologers/{astro_uid}")).status_code == 404
        assert (await api.post("/api/astrologer/presence", json={"online": True}, headers=astro)).status_code == 403
        pending = (await api.get("/api/admin/astrologers", headers=OWNER)).json()["astrologers"]
        assert astro_uid in [a["uid"] for a in pending]

        # 2. the owner approves; the astrologer goes online and is listed
        assert (await api.post(f"/api/admin/astrologers/{astro_uid}/approve", headers=OWNER)).json()["status"] == "approved"
        assert (await api.post("/api/astrologer/presence", json={"online": True}, headers=astro)).json()["online"] is True
        listed = (await api.get("/api/astrologers?language=hindi&limit=50")).json()["items"]
        card = next(i for i in listed if i["uid"] == astro_uid)
        assert card["online"] is True and card["rates_paise_per_min"] == {"chat": 1000, "call": 2000}
        assert "payout_upi" not in card and "earnings_paise" not in card

        # 3. a user cannot start before accepting the terms and adding money
        user_uid = uid()
        user = bearer(user_uid, email=f"{user_uid}@example.com")
        body = {"astrologer_uid": astro_uid, "mode": "chat", "topic": "Marriage timing"}
        r = await api.post("/api/consult/sessions", json=body, headers=user)
        assert r.status_code == 428 and r.json()["detail"]["error"] == "terms_required"
        await api.post("/api/me/accept-terms", headers=user)
        r = await api.post("/api/consult/sessions", json=body, headers=user)
        assert r.status_code == 402 and r.json()["detail"] == {
            "error": "insufficient_balance", "message": r.json()["detail"]["message"], "needed_paise": 5000, "balance_paise": 0}
        await api.post("/api/admin/wallet/adjust", json={"uid": user_uid, "amount_paise": 20000, "note": "top-up"}, headers=OWNER)

        # 4. the request reaches the astrologer, who accepts
        started = (await api.post("/api/consult/sessions", json={**body, "birth_data": {
            "name": "Seeker", "date_of_birth": "1992-03-02", "time_of_birth": "09:10", "latitude": 28.61, "longitude": 77.2}},
            headers=user)).json()
        session_id = started["session"]["id"]
        assert started["session"]["status"] == "requested" and started["wallet_balance_paise"] == 20000
        inbox = (await api.get("/api/astrologer/requests", headers=astro)).json()
        waiting = next(r for r in inbox["requests"] if r["id"] == session_id)
        assert waiting["user_uid"] == user_uid and waiting["birth_data"]["date_of_birth"] == "1992-03-02"
        accepted = (await api.post(f"/api/consult/sessions/{session_id}/accept", headers=astro)).json()
        assert accepted["status"] == "active" and accepted["billed_minutes"] == 1
        assert (await api.get("/api/me", headers=user)).json()["wallet_balance_paise"] == 19000

        # 5. they chat; the astrologer's long-poll is released the moment the user writes
        async def astrologer_waits():
            started_at = time.monotonic()
            r = await api.get(f"/api/consult/sessions/{session_id}/messages?after=0&wait=10", headers=astro)
            return r.json(), time.monotonic() - started_at

        # skip the "Consultation started" system message first so the poll genuinely has to wait
        first = (await api.get(f"/api/consult/sessions/{session_id}/messages", headers=astro)).json()
        last_id = first["messages"][-1]["id"]

        async def waits_for_news():
            t = time.monotonic()
            r = await api.get(f"/api/consult/sessions/{session_id}/messages?after={last_id}&wait=10", headers=astro)
            return r.json(), time.monotonic() - t

        poll = asyncio.create_task(waits_for_news())
        await asyncio.sleep(0.3)
        assert not poll.done()                                              # nothing yet: it is waiting
        sent = await api.post(f"/api/consult/sessions/{session_id}/messages",
                              json={"body": "Namaste, when will I get married?"}, headers=user)
        assert sent.status_code == 200
        news, seconds = await asyncio.wait_for(poll, 5)
        assert [m["body"] for m in news["messages"]] == ["Namaste, when will I get married?"] and seconds < 3
        assert news["session"]["status"] == "active"
        await api.post(f"/api/consult/sessions/{session_id}/messages", json={"body": "Your Jupiter period is favourable."}, headers=astro)
        reply = (await api.get(f"/api/consult/sessions/{session_id}/messages?after={news['messages'][-1]['id']}", headers=user)).json()
        assert [m["body"] for m in reply["messages"]] == ["Your Jupiter period is favourable."]

        # 6. the user ends it, reviews it, and the money has moved correctly
        ended = (await api.post(f"/api/consult/sessions/{session_id}/end", headers=user)).json()
        assert ended["session"]["status"] == "ended" and ended["session"]["end_reason"] == "completed"
        assert ended["wallet_balance_paise"] == 19000 and ended["session"]["charged_paise"] == 1000
        assert (await api.post(f"/api/consult/sessions/{session_id}/review", json={"rating": 5, "comment": "Very clear advice"},
                               headers=user)).status_code == 200
        profile = (await api.get(f"/api/astrologers/{astro_uid}")).json()
        assert profile["rating"] == 5.0 and profile["rating_count"] == 1 and profile["sessions_count"] == 1
        assert profile["reviews"][0]["comment"] == "Very clear advice"

        # 7. the astrologer sees what they earned; the owner pays out and the balance goes down
        mine = (await api.get("/api/astrologer/earnings", headers=astro)).json()
        assert mine["owed_paise"] == 700 and mine["entries"][0]["kind"] == "consult"
        assert (await api.post("/api/admin/payouts", json={"astrologer_uid": astro_uid, "amount_paise": 99999}, headers=OWNER)).status_code == 409
        paid = (await api.post("/api/admin/payouts", json={"astrologer_uid": astro_uid, "amount_paise": 700, "note": "UPI ref 123"},
                               headers=OWNER)).json()
        assert paid["still_owed_paise"] == 0 and paid["payout_upi"] == "acharya@okbank"
        entries = (await api.get("/api/astrologer/earnings", headers=astro)).json()["entries"]
        assert [e["kind"] for e in entries] == ["payout", "consult"]
        stats = (await api.get("/api/admin/summary", headers=OWNER)).json()
        assert stats["consultations"]["total"] >= 1 and stats["money_paise"]["platform_commission"] >= 300
        assert stats["astrologers"]["approved"] >= 1


class TestPermissions:
    async def test_everything_needs_a_signed_in_user_except_browsing(self, api):
        assert (await api.get("/api/astrologers")).status_code == 200
        for method, path in (("post", "/api/consult/sessions"), ("get", "/api/consult/sessions"),
                             ("get", "/api/astrologer/me"), ("post", "/api/astrologer/apply"),
                             ("post", "/api/me/accept-terms"), ("get", "/api/admin/summary"), ("get", "/api/bookings")):
            r = await getattr(api, method)(path, **({"json": {}} if method == "post" else {}))
            assert r.status_code == 401, path

    async def test_admin_routes_need_an_admin(self, api):
        normal = bearer(uid(), email="someone@example.com")
        unverified = bearer("owner-2", email=OWNER_EMAIL, verified=False)
        for h in (normal, unverified):
            assert (await api.get("/api/admin/summary", headers=h)).status_code == 403
            assert (await api.post(f"/api/admin/astrologers/x/approve", headers=h)).status_code == 403
            assert (await api.post("/api/admin/wallet/adjust", json={"uid": "x", "amount_paise": 100, "note": "free"}, headers=h)).status_code == 403
        assert (await api.get("/api/admin/summary", headers=OWNER)).status_code == 200

    async def test_strangers_cannot_see_or_touch_a_consultation(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        _, user = await make_funded_user(api)
        sid = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        stranger = bearer(uid())
        for method, path, body in (("get", f"/api/consult/sessions/{sid}", None), ("get", f"/api/consult/sessions/{sid}/messages", None),
                                   ("post", f"/api/consult/sessions/{sid}/messages", {"body": "hi"}),
                                   ("post", f"/api/consult/sessions/{sid}/end", None), ("post", f"/api/consult/sessions/{sid}/accept", None),
                                   ("post", f"/api/consult/sessions/{sid}/review", {"rating": 1}),
                                   ("post", f"/api/consult/sessions/{sid}/report", {"reason": "abuse"})):
            kwargs = {"json": body} if body is not None else {}
            r = await getattr(api, method)(path, headers=stranger, **kwargs)
            assert r.status_code == 404 and r.json()["detail"]["error"] == "not_found", path

    async def test_a_user_cannot_accept_their_own_request_or_play_astrologer(self, api):
        astro_uid, _ = await make_approved_online_astrologer(api)
        user_uid, user = await make_funded_user(api)
        sid = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        assert (await api.post(f"/api/consult/sessions/{sid}/accept", headers=user)).status_code == 404
        assert (await api.get("/api/astrologer/requests", headers=user)).status_code == 403

    async def test_blocking_an_account_stops_it_consulting(self, api):
        astro_uid, _ = await make_approved_online_astrologer(api)
        user_uid, user = await make_funded_user(api)
        assert (await api.post(f"/api/admin/accounts/{user_uid}/block", json={"blocked": True}, headers=OWNER)).json()["blocked"] is True
        r = await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)
        assert r.status_code == 403 and r.json()["detail"]["error"] == "blocked"
        await api.post(f"/api/admin/accounts/{user_uid}/block", json={"blocked": False}, headers=OWNER)
        assert (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).status_code == 200
        assert (await api.post("/api/admin/accounts/nobody/block", json={"blocked": True}, headers=OWNER)).status_code == 404


class TestChatRules:
    async def active_session(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        _, user = await make_funded_user(api)
        sid = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        await api.post(f"/api/consult/sessions/{sid}/accept", headers=astro)
        return sid, user, astro

    async def test_contact_details_are_refused_with_a_code_the_app_can_show(self, api):
        sid, user, _ = await self.active_session(api)
        r = await api.post(f"/api/consult/sessions/{sid}/messages", json={"body": "my number is 9876543210"}, headers=user)
        assert r.status_code == 422 and r.json()["detail"]["error"] == "contact_blocked"

    async def test_flooding_is_slowed_down(self, api, monkeypatch):
        monkeypatch.setattr(routes_consult, "MESSAGES_PER_MINUTE", 3)
        sid, user, _ = await self.active_session(api)
        codes = [(await api.post(f"/api/consult/sessions/{sid}/messages", json={"body": f"message {i}"}, headers=user)).status_code
                 for i in range(5)]
        assert codes == [200, 200, 200, 429, 429]

    async def test_a_poll_without_news_returns_after_its_wait_and_a_finished_session_returns_at_once(self, api):
        sid, user, astro = await self.active_session(api)
        latest = (await api.get(f"/api/consult/sessions/{sid}/messages", headers=user)).json()["messages"][-1]["id"]
        t = time.monotonic()
        quiet = (await api.get(f"/api/consult/sessions/{sid}/messages?after={latest}&wait=1", headers=user)).json()
        assert quiet["messages"] == [] and 0.8 < time.monotonic() - t < 3
        await api.post(f"/api/consult/sessions/{sid}/end", headers=astro)
        t = time.monotonic()
        done = (await api.get(f"/api/consult/sessions/{sid}/messages?after=999999&wait=20", headers=user)).json()
        assert done["session"]["status"] == "ended" and time.monotonic() - t < 2

    async def test_an_ending_by_the_other_side_wakes_a_waiting_poll(self, api):
        sid, user, astro = await self.active_session(api)
        latest = (await api.get(f"/api/consult/sessions/{sid}/messages", headers=user)).json()["messages"][-1]["id"]
        poll = asyncio.create_task(api.get(f"/api/consult/sessions/{sid}/messages?after={latest}&wait=10", headers=user))
        await asyncio.sleep(0.3)
        await api.post(f"/api/consult/sessions/{sid}/end", headers=astro)
        r = await asyncio.wait_for(poll, 5)
        assert r.json()["session"]["status"] == "ended"

    async def test_query_limits_are_validated(self, api):
        sid, user, _ = await self.active_session(api)
        assert (await api.get(f"/api/consult/sessions/{sid}/messages?wait=999", headers=user)).status_code == 422
        assert (await api.get("/api/astrologers?limit=0")).status_code == 422
        assert (await api.get("/api/astrologers?mode=telepathy")).status_code == 422
        assert (await api.get("/api/astrologers?sort=nonsense")).status_code == 400


class TestRequestsInbox:
    async def test_the_astrologers_poll_wakes_up_for_a_new_request(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        _, user = await make_funded_user(api)
        poll = asyncio.create_task(api.get("/api/astrologer/requests?wait=10", headers=astro))
        await asyncio.sleep(0.3)
        assert not poll.done()
        await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)
        inbox = (await asyncio.wait_for(poll, 5)).json()
        assert len(inbox["requests"]) == 1

    async def test_declining_and_cancelling(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        _, user = await make_funded_user(api)
        sid = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        assert (await api.post(f"/api/consult/sessions/{sid}/decline", headers=astro)).json()["status"] == "declined"
        sid2 = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        assert (await api.post(f"/api/consult/sessions/{sid2}/cancel", headers=user)).json()["status"] == "cancelled"
        listed = (await api.get("/api/consult/sessions", headers=user)).json()["sessions"]
        assert {s["status"] for s in listed} == {"declined", "cancelled"}
        theirs = (await api.get("/api/consult/sessions?role=astrologer", headers=astro)).json()["sessions"]
        assert len(theirs) == 2


class TestProfileSelfService:
    async def test_an_astrologer_manages_their_own_profile(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        me = (await api.get("/api/astrologer/me", headers=astro)).json()
        assert me["status"] == "approved" and me["payout_upi"] == "acharya@okbank"
        updated = (await api.put("/api/astrologer/me", json={"bio": "Updated", "video_rate_paise": 3000}, headers=astro)).json()
        assert updated["bio"] == "Updated" and updated["rates_paise_per_min"]["video"] == 3000
        assert (await api.put("/api/astrologer/me", json={"payout_upi": "bad"}, headers=astro)).json()["detail"]["error"] == "bad_upi"
        assert (await api.put("/api/astrologer/me", json={"chat_rate_paise": 10}, headers=astro)).json()["detail"]["error"] == "bad_rate"
        stranger = bearer(uid())
        assert (await api.get("/api/astrologer/me", headers=stranger)).json()["detail"]["error"] == "not_an_astrologer"
        assert (await api.get("/api/astrologer/earnings", headers=stranger)).status_code == 404

    async def test_applying_twice_and_rejection(self, api):
        who = uid("astro")
        h = bearer(who)
        await api.post("/api/astrologer/apply", json=PROFILE, headers=h)
        assert (await api.post("/api/astrologer/apply", json=PROFILE, headers=h)).json()["detail"]["error"] == "already_applied"
        rejected = (await api.post(f"/api/admin/astrologers/{who}/reject", json={"note": "Add certificates"}, headers=OWNER)).json()
        assert rejected["status"] == "rejected" and rejected["status_note"] == "Add certificates"
        assert (await api.post("/api/astrologer/apply", json=PROFILE, headers=h)).json()["status"] == "pending"
        assert (await api.post(f"/api/admin/astrologers/{who}/suspend", json={"note": "x"}, headers=OWNER)).status_code == 409

    async def test_suspending_takes_an_astrologer_off_the_list(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        await api.post(f"/api/admin/astrologers/{astro_uid}/suspend", json={"note": "Complaints"}, headers=OWNER)
        assert all(i["uid"] != astro_uid for i in (await api.get("/api/astrologers?limit=50")).json()["items"])
        assert (await api.get("/api/astrologer/requests", headers=astro)).status_code == 403
        again = (await api.post(f"/api/admin/astrologers/{astro_uid}/approve", headers=OWNER)).json()
        assert again["status"] == "approved"

    async def test_input_validation_over_http(self, api):
        h = bearer(uid("astro"))
        assert (await api.post("/api/astrologer/apply", json={**PROFILE, "name": "A"}, headers=h)).status_code == 422
        assert (await api.post("/api/astrologer/apply", json={**PROFILE, "experience_years": 99}, headers=h)).status_code == 422
        assert (await api.post("/api/astrologer/apply", json={**PROFILE, "chat_rate_paise": None, "call_rate_paise": None}, headers=h)
                ).json()["detail"]["error"] == "no_rates"


class TestReportsAndAdminTools:
    async def test_abuse_reports_reach_the_owner(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        user_uid, user = await make_funded_user(api)
        sid = (await api.post("/api/consult/sessions", json={"astrologer_uid": astro_uid}, headers=user)).json()["session"]["id"]
        r = await api.post(f"/api/consult/sessions/{sid}/report", json={"reason": "abuse", "details": "rude"}, headers=user)
        report_id = r.json()["id"]
        open_reports = (await api.get("/api/admin/reports", headers=OWNER)).json()["reports"]
        mine = next(x for x in open_reports if x["id"] == report_id)
        assert mine["target_uid"] == astro_uid and mine["reporter_uid"] == user_uid
        assert (await api.post(f"/api/admin/reports/{report_id}/resolve", headers=OWNER)).json()["status"] == "reviewed"
        assert report_id not in [x["id"] for x in (await api.get("/api/admin/reports", headers=OWNER)).json()["reports"]]
        assert (await api.post("/api/admin/reports/999999/resolve", headers=OWNER)).status_code == 404

    async def test_wallet_adjustments(self, api):
        who = uid()
        assert (await api.post("/api/admin/wallet/adjust", json={"uid": who, "amount_paise": 5000, "note": "goodwill"}, headers=OWNER)).json()["balance_paise"] == 5000
        assert (await api.post("/api/admin/wallet/adjust", json={"uid": who, "amount_paise": -2000, "note": "correction"}, headers=OWNER)).json()["balance_paise"] == 3000
        assert (await api.post("/api/admin/wallet/adjust", json={"uid": who, "amount_paise": -9000, "note": "too much"}, headers=OWNER)).status_code == 409
        assert (await api.post("/api/admin/wallet/adjust", json={"uid": who, "amount_paise": 0, "note": "nothing"}, headers=OWNER)).status_code == 400
        statement = (await api.get(f"/api/admin/wallet/{who}", headers=OWNER)).json()
        assert statement["balance_paise"] == 3000 and [e["amount_paise"] for e in statement["entries"]] == [-2000, 5000]
        mine = (await api.get("/api/wallet", headers=bearer(who))).json()
        assert mine["balance_paise"] == 3000

    async def test_me_shows_the_new_account_facts(self, api):
        astro_uid, astro = await make_approved_online_astrologer(api)
        me = (await api.get("/api/me", headers=astro)).json()
        assert me["astrologer_status"] == "approved" and me["terms_accepted"] is False
        assert (await api.get("/api/me", headers=bearer(uid()))).json()["astrologer_status"] is None
