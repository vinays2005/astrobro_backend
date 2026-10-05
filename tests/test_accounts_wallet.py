"""Accounts, premium time, the daily chat allowance, and the wallet ledger (against a real SQLite database)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.config import get_settings
from app.database.connection import session_scope
from app.database.models import Entitlement, UsageDaily, utcnow
from app.security.identity import AuthUser
from app.services import accounts, wallet


def ref() -> str:
    """A reference id nobody else has used (real ones are payment ids and session ids, which are unique)."""
    return "r-" + uuid.uuid4().hex[:12]


def make_user(email: str | None = "a@example.com", name: str | None = "A") -> AuthUser:
    return AuthUser(uid="u-" + uuid.uuid4().hex[:12], email=email, email_verified=True, name=name, is_admin=False)


class TestAccounts:
    async def test_account_is_created_once_and_kept_fresh(self):
        user = make_user()
        async with session_scope() as db:
            first = await accounts.ensure_account(db, user)
        assert first.uid == user.uid and first.email == "a@example.com" and not first.is_blocked
        renamed = AuthUser(uid=user.uid, email="new@example.com", email_verified=True, name="New Name", is_admin=False)
        async with session_scope() as db:
            again = await accounts.ensure_account(db, renamed)
        assert again.email == "new@example.com" and again.display_name == "New Name"

    async def test_no_premium_by_default(self):
        async with session_scope() as db:
            assert not await accounts.is_premium(db, "nobody-" + uuid.uuid4().hex)

    async def test_grant_premium_starts_now_and_stacks(self):
        uid = make_user().uid
        async with session_scope() as db:
            first = await accounts.grant_premium(db, uid, 7)
        assert timedelta(days=6, hours=23) < first - utcnow() <= timedelta(days=7)
        async with session_scope() as db:
            second = await accounts.grant_premium(db, uid, 30)
            assert await accounts.is_premium(db, uid)
        assert second - first == timedelta(days=30)                  # added after the running plan, not on top of "now"

    async def test_expired_premium_counts_as_free_and_restarts_from_now(self):
        uid = make_user().uid
        async with session_scope() as db:
            await accounts.grant_premium(db, uid, 7)
            ent = await db.get(Entitlement, uid)
            ent.valid_until = utcnow() - timedelta(days=1)
        async with session_scope() as db:
            assert not await accounts.is_premium(db, uid)
            renewed = await accounts.grant_premium(db, uid, 7)
        assert renewed - utcnow() <= timedelta(days=7)

    async def test_plan_table_matches_the_app_and_the_legacy_endpoint(self):
        from app.api.routes_payment import PLAN_PRICES

        assert {k: v[0] for k, v in accounts.PLANS.items()} == PLAN_PRICES
        assert {k: v[1] for k, v in accounts.PLANS.items()} == {"weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}


class TestChatAllowance:
    async def test_free_users_get_the_daily_limit_then_are_stopped(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_chats_per_day", 3)
        uid = make_user().uid
        results = []
        for _ in range(5):
            async with session_scope() as db:
                results.append(await accounts.consume_chat(db, uid))
        assert [r[0] for r in results] == [True, True, True, False, False]
        assert results[2] == (True, 3, 3) and results[3] == (False, 3, 3)

    async def test_releasing_a_chat_gives_it_back(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_chats_per_day", 2)
        uid = make_user().uid
        async with session_scope() as db:
            await accounts.consume_chat(db, uid)
            await accounts.consume_chat(db, uid)
        async with session_scope() as db:
            await accounts.release_chat(db, uid)
            assert await accounts.usage_today(db, uid) == 1
            assert (await accounts.consume_chat(db, uid))[0] is True

    async def test_release_never_goes_below_zero(self):
        uid = make_user().uid
        async with session_scope() as db:
            await accounts.release_chat(db, uid)
            assert await accounts.usage_today(db, uid) == 0

    async def test_premium_gets_the_higher_limit(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_chats_per_day", 1)
        monkeypatch.setattr(get_settings(), "premium_chats_per_day", 4)
        uid = make_user().uid
        async with session_scope() as db:
            await accounts.grant_premium(db, uid, 7)
        allowed = []
        for _ in range(5):
            async with session_scope() as db:
                allowed.append((await accounts.consume_chat(db, uid))[0])
        assert allowed == [True, True, True, True, False]

    async def test_each_day_has_its_own_counter(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_chats_per_day", 1)
        uid = make_user().uid
        yesterday = accounts.today_ist() - timedelta(days=1)
        async with session_scope() as db:
            db.add(UsageDaily(uid=uid, day=yesterday, chats=1))
        async with session_scope() as db:
            assert (await accounts.consume_chat(db, uid))[0] is True

    async def test_the_day_changes_at_indian_midnight(self):
        from datetime import datetime, timezone

        assert accounts.today_ist() == datetime.now(accounts.IST).date()
        assert accounts.IST.utcoffset(datetime.now(timezone.utc)) == timedelta(hours=5, minutes=30)


class TestWallet:
    async def test_credit_and_debit_keep_a_ledger(self):
        uid = make_user().uid
        p, s1 = ref(), ref()
        async with session_scope() as db:
            assert await wallet.credit(db, uid, 10000, "topup", "payment", p) == wallet.APPLIED
            assert await wallet.debit(db, uid, 2500, "consult_charge", "session", s1) == wallet.APPLIED
            assert await wallet.balance(db, uid) == 7500
            entries = await wallet.history(db, uid)
        assert [e.amount_paise for e in entries] == [-2500, 10000]            # newest first
        assert [e.balance_after_paise for e in entries] == [7500, 10000]

    async def test_a_balance_can_never_go_negative(self):
        uid = make_user().uid
        p, s1 = ref(), ref()
        async with session_scope() as db:
            await wallet.credit(db, uid, 1000, "topup", "payment", p)
            assert await wallet.debit(db, uid, 1001, "consult_charge", "session", s1) == wallet.INSUFFICIENT
            assert await wallet.balance(db, uid) == 1000
            assert len(await wallet.history(db, uid)) == 1               # nothing was written for the refused debit

    async def test_replaying_a_reference_changes_nothing(self):
        uid = make_user().uid
        same, minute = ref(), ref()
        async with session_scope() as db:
            assert await wallet.credit(db, uid, 5000, "topup", "payment", same) == wallet.APPLIED
            assert await wallet.credit(db, uid, 5000, "topup", "payment", same) == wallet.DUPLICATE
            assert await wallet.debit(db, uid, 100, "consult_charge", "session", minute) == wallet.APPLIED
            assert await wallet.debit(db, uid, 100, "consult_charge", "session", minute) == wallet.DUPLICATE
            assert await wallet.balance(db, uid) == 4900

    async def test_entries_without_a_reference_are_always_applied(self):
        uid = make_user().uid
        async with session_scope() as db:
            await wallet.credit(db, uid, 100, "adjustment")
            await wallet.credit(db, uid, 100, "adjustment")
            assert await wallet.balance(db, uid) == 200

    async def test_zero_and_negative_amounts_are_refused(self):
        uid = make_user().uid
        async with session_scope() as db:
            for bad in (0, -5):
                with pytest.raises(ValueError):
                    await wallet.credit(db, uid, bad, "topup")
                with pytest.raises(ValueError):
                    await wallet.debit(db, uid, bad, "consult_charge")

    async def test_wallets_are_separate_per_user(self):
        a, b = make_user().uid, make_user().uid
        async with session_scope() as db:
            await wallet.credit(db, a, 3000, "topup", "payment", ref())
            assert await wallet.balance(db, b) == 0
            assert await wallet.debit(db, b, 1, "consult_charge", "session", ref()) == wallet.INSUFFICIENT
