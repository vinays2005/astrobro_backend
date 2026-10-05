"""Deleting an account erases the person's data, keeps only what a law requires, and never loses anyone's money."""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.database.connection import session_scope
from app.database.models import (AbuseReport, Account, AccountDeletion, Astrologer, Booking, ChatMemory,
                                 ConsultMessage, ConsultSession, Entitlement, Review, UsageDaily, WalletEntry, utcnow)
from app.main import app
from app.security.auth import require_api_key
from app.services import accounts, consult, erasure, memory, wallet
from app.services.errors import ServiceError
from tests.firebase_helpers import bearer, install_verifier
from tests.market_helpers import RATE, T0, at, make_astrologer, make_client, new_uid, person

BIRTH = {"name": "Asha", "dob": "1990-08-15", "tob": "14:30", "lat": 19.07, "lon": 72.87}


async def erase(uid: str, email: str | None = None, now=None) -> dict:
    async with session_scope() as db:
        return await erasure.delete_account(db, uid, email, now)


async def refused(uid: str) -> str:
    with pytest.raises(ServiceError) as err:
        await erase(uid)
    return err.value.code


async def empty_wallet(uid: str) -> None:
    async with session_scope() as db:
        left = await wallet.balance(db, uid)
        if left:
            await wallet.debit(db, uid, left, "adjustment", "admin", new_uid("adj"))


async def finished_consultation(*, report: bool = False) -> tuple:
    """A client who chatted with an astrologer for one minute and has spent their whole wallet."""
    client = await make_client(paise=5 * RATE)
    astro = await make_astrologer()
    async with session_scope() as db:
        s = await consult.start_session(db, client, astro.uid, "chat", topic="Marriage timing", birth_data=BIRTH, now=T0)
    async with session_scope() as db:
        await consult.accept_session(db, astro.uid, s.id, now=at(seconds=5))
    async with session_scope() as db:
        await consult.send_message(db, client.uid, s.id, "When will I get married?", now=at(seconds=10))
        await consult.send_message(db, astro.uid, s.id, "Venus is strong in your chart.", now=at(seconds=20))
    async with session_scope() as db:
        await consult.end_session(db, client.uid, s.id, now=at(seconds=40))
    if report:
        async with session_scope() as db:
            await consult.report_abuse(db, client.uid, s.id, "abuse", "He was rude to me")
    await empty_wallet(client.uid)
    return client, astro, s.id


async def messages(session_id: str) -> list[ConsultMessage]:
    async with session_scope() as db:
        return list((await db.execute(select(ConsultMessage).where(ConsultMessage.session_id == session_id))).scalars())


class TestWhatIsErased:
    async def test_memory_usage_plan_and_the_accounts_email_go_and_a_deletion_record_is_kept(self):
        user = person()
        async with session_scope() as db:
            await accounts.ensure_account(db, user)
            await accounts.consume_chat(db, user.uid)
            await accounts.grant_premium(db, user.uid, 30)
            await memory.remember(db, user.uid, "Will I get a government job this year?", "Your 10th lord is strong.")

        result = await erase(user.uid, user.email)

        assert result == {"deleted": True, "registration_kept_days": 180}
        async with session_scope() as db:
            assert (await db.execute(select(ChatMemory).where(ChatMemory.uid == user.uid))).first() is None
            assert (await db.execute(select(UsageDaily).where(UsageDaily.uid == user.uid))).first() is None
            assert await db.get(Entitlement, user.uid) is None
            account = await db.get(Account, user.uid)
            assert account.email is None and account.display_name is None
            record = await db.get(AccountDeletion, user.uid)
            assert record.email == user.email

    async def test_a_finished_consultation_loses_its_words_but_keeps_its_billing(self):
        client, astro, session_id = await finished_consultation()

        await erase(client.uid)

        assert await messages(session_id) == []
        async with session_scope() as db:
            s = await db.get(ConsultSession, session_id)
            assert s.topic is None and not s.birth_snapshot
            assert s.charged_paise == RATE                        # the money trail stays for the tax records
            ledger = (await db.execute(select(WalletEntry).where(WalletEntry.uid == client.uid))).scalars().all()
            assert len(ledger) >= 2

    async def test_a_consultation_under_an_open_complaint_keeps_its_messages(self):
        client, astro, session_id = await finished_consultation(report=True)

        await erase(client.uid)

        assert len(await messages(session_id)) >= 2
        async with session_scope() as db:
            report = (await db.execute(select(AbuseReport).where(AbuseReport.session_id == session_id))).scalar_one()
            assert report.details == "He was rude to me"

    async def test_review_comments_and_booking_contact_details_are_removed(self):
        client, astro, session_id = await finished_consultation()
        async with session_scope() as db:
            await consult.add_review(db, client.uid, session_id, 5, "Very helpful, thank you")
            db.add(Booking(user_uid=client.uid, service_id="griha-shanti", service_name="Griha Shanti", status="completed",
                           price_paise=250_000, scheduled_for=utcnow() - timedelta(days=3), location_text="12 MG Road, Pune",
                           notes="Gate code 1234", contact_name="Asha", contact_phone="9876543210"))

        await erase(client.uid)

        async with session_scope() as db:
            review = (await db.execute(select(Review).where(Review.session_id == session_id))).scalar_one()
            assert review.comment is None and review.rating == 5
            booking = (await db.execute(select(Booking).where(Booking.user_uid == client.uid))).scalar_one()
            assert (booking.contact_name, booking.contact_phone, booking.location_text, booking.notes) == ("", "", None, None)
            assert booking.status == "completed"

    async def test_an_astrologer_with_nothing_owed_loses_their_public_profile_and_upi(self):
        astro = await make_astrologer(online=True)
        async with session_scope() as db:
            (await db.get(Astrologer, astro.uid)).payout_upi = "pandit@okbank"

        await erase(astro.uid)

        async with session_scope() as db:
            a = await db.get(Astrologer, astro.uid)
            assert (a.name, a.bio, a.photo_url, a.payout_upi, a.is_online, a.status) == (
                "Former astrologer", "", None, None, False, "suspended")

    async def test_deleting_twice_is_harmless(self):
        user = person()
        await erase(user.uid, user.email)
        await erase(user.uid, None)
        async with session_scope() as db:
            assert (await db.get(AccountDeletion, user.uid)).email == user.email


class TestNobodyLosesMoney:
    async def test_a_wallet_with_money_in_it_cannot_be_deleted_and_nothing_is_erased(self):
        client = await make_client(paise=20_000)
        async with session_scope() as db:
            await memory.remember(db, client.uid, "Will I get a government job this year?", "Your 10th lord is strong.")

        assert await refused(client.uid) == "wallet_not_empty"

        async with session_scope() as db:
            assert (await db.execute(select(ChatMemory).where(ChatMemory.uid == client.uid))).first() is not None
            assert await db.get(AccountDeletion, client.uid) is None

    async def test_a_running_consultation_blocks_deletion_for_both_people(self):
        client = await make_client(paise=5 * RATE)
        astro = await make_astrologer()
        async with session_scope() as db:
            s = await consult.start_session(db, client, astro.uid, "chat", now=T0)
        async with session_scope() as db:
            await consult.accept_session(db, astro.uid, s.id, now=at(seconds=5))
        await empty_wallet(client.uid)

        assert await refused(client.uid) == "consult_in_progress"
        assert await refused(astro.uid) == "consult_in_progress"

    @pytest.mark.parametrize("status", ["paid", "confirmed"])
    async def test_a_paid_booking_that_is_not_finished_blocks_deletion(self, status):
        user = person()
        async with session_scope() as db:
            db.add(Booking(user_uid=user.uid, service_id="puja", service_name="Puja", status=status, price_paise=100_000,
                           scheduled_for=utcnow() + timedelta(days=3), contact_name="Asha", contact_phone="9876543210"))

        assert await refused(user.uid) == "booking_in_progress"

    async def test_an_unpaid_booking_draft_is_simply_cancelled(self):
        user = person()
        async with session_scope() as db:
            db.add(Booking(user_uid=user.uid, service_id="puja", service_name="Puja", status="pending_payment",
                           price_paise=100_000, scheduled_for=utcnow() + timedelta(days=3), contact_name="Asha",
                           contact_phone="9876543210"))

        await erase(user.uid)

        async with session_scope() as db:
            booking = (await db.execute(select(Booking).where(Booking.user_uid == user.uid))).scalar_one()
            assert booking.status == "cancelled" and booking.contact_phone == ""

    async def test_an_astrologer_with_unpaid_earnings_cannot_be_deleted(self):
        client, astro, _ = await finished_consultation()

        assert await refused(astro.uid) == "earnings_unpaid"


class TestRetention:
    async def test_registration_details_are_purged_after_180_days_and_not_before(self):
        old, recent = person(), person()
        await erase(old.uid, old.email, now=utcnow() - timedelta(days=181))
        await erase(recent.uid, recent.email, now=utcnow() - timedelta(days=179))

        async with session_scope() as db:
            await erasure.purge_expired(db)
        async with session_scope() as db:
            assert await db.get(AccountDeletion, old.uid) is None
            assert await db.get(AccountDeletion, recent.uid) is not None


class TestOverHttp:
    @pytest.fixture
    async def api(self):
        install_verifier()
        app.dependency_overrides[require_api_key] = lambda: None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=60) as ac:
            yield ac
        app.dependency_overrides.clear()

    async def test_a_signed_in_user_can_delete_their_account(self, api):
        who = new_uid()
        headers = bearer(who, email=f"{who}@example.com")
        assert (await api.get("/api/me", headers=headers)).status_code == 200

        r = await api.delete("/api/me", headers=headers)

        assert r.status_code == 200 and r.json()["deleted"] is True
        async with session_scope() as db:
            assert (await db.get(AccountDeletion, who)).email == f"{who}@example.com"

    async def test_a_refusal_carries_a_code_the_app_can_act_on(self, api):
        client = await make_client(paise=20_000)
        r = await api.delete("/api/me", headers=bearer(client.uid, email=client.email))
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "wallet_not_empty"
        assert r.json()["detail"]["balance_paise"] == 20_000

    async def test_nobody_can_delete_without_signing_in(self, api):
        assert (await api.delete("/api/me")).status_code == 401
