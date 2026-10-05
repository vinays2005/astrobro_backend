"""Races on the money paths. SQLite cannot run these (it has no row locks), so they run on Postgres only:

    pip install pgserver && python scripts/pg_tests.py -k concurrency
"""
from __future__ import annotations

import asyncio
import os

import pytest

from app.config import get_settings
from app.database.connection import session_scope
from app.services import accounts, consult, wallet
from app.services.errors import ServiceError
from tests.market_helpers import RATE, T0, balance, earnings, make_astrologer, make_client, new_uid, start

pytestmark = pytest.mark.skipif("postgres" not in os.environ.get("DATABASE_URL", ""), reason="needs row locks (Postgres)")


async def attempt(coro):
    try:
        return await coro
    except ServiceError as exc:
        return exc


class TestWalletRaces:
    async def test_the_same_payment_credited_twice_at_once_counts_once(self):
        uid = new_uid()
        ref = new_uid("pay")

        async def credit():
            async with session_scope() as db:
                return await wallet.credit(db, uid, 5000, "topup", "payment", ref)

        outcomes = await asyncio.gather(*[credit() for _ in range(8)], return_exceptions=True)
        errors = [o for o in outcomes if isinstance(o, Exception)]
        assert outcomes.count(wallet.APPLIED) == 1 and len(errors) + outcomes.count(wallet.DUPLICATE) == 7
        assert await balance(uid) == 5000

    async def test_many_different_top_ups_add_up_exactly(self):
        uid = new_uid()

        async def credit(i):
            async with session_scope() as db:
                return await wallet.credit(db, uid, 100, "topup", "payment", f"{uid}-{i}")

        results = await asyncio.gather(*[credit(i) for i in range(20)], return_exceptions=True)
        applied = sum(1 for r in results if r == wallet.APPLIED)
        assert await balance(uid) == 100 * applied == 2000

    async def test_two_debits_cannot_spend_the_same_money(self):
        uid = new_uid()
        async with session_scope() as db:
            await wallet.credit(db, uid, 1000, "topup", "payment", new_uid("pay"))

        async def spend(i):
            async with session_scope() as db:
                return await wallet.debit(db, uid, 700, "consult_charge", "session", f"{uid}-{i}")

        results = await asyncio.gather(*[spend(i) for i in range(6)], return_exceptions=True)
        assert results.count(wallet.APPLIED) == 1 and await balance(uid) == 300


class TestAllowanceRaces:
    async def test_parallel_chats_never_exceed_the_daily_limit(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "free_chats_per_day", 5)
        uid = new_uid()

        async def chat():
            async with session_scope() as db:
                return (await accounts.consume_chat(db, uid))[0]

        results = await asyncio.gather(*[chat() for _ in range(15)], return_exceptions=True)
        assert results.count(True) == 5
        async with session_scope() as db:
            assert await accounts.usage_today(db, uid) == 5


class TestConsultationRaces:
    async def test_two_accepts_at_once_charge_one_minute_and_start_one_session(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro)

        async def accept():
            async with session_scope() as db:
                return await consult.accept_session(db, astro.uid, s.id, now=T0)

        results = await asyncio.gather(*[accept() for _ in range(4)], return_exceptions=True)
        started = [r for r in results if not isinstance(r, Exception)]
        failed = [r for r in results if isinstance(r, ServiceError)]
        assert len(started) == 1 and all(r.code == "not_pending" for r in failed)
        assert await balance(client.uid) == 20_000 - RATE and await earnings(astro.uid) == RATE * 70 // 100

    async def test_an_astrologer_cannot_take_two_consultations_at_once(self):
        a, b, astro = await make_client(), await make_client(), await make_astrologer()
        sa, sb = await start(a, astro), await start(b, astro)

        async def accept(sid):
            async with session_scope() as db:
                return await consult.accept_session(db, astro.uid, sid, now=T0)

        results = await asyncio.gather(accept(sa.id), accept(sb.id), return_exceptions=True)
        assert sum(1 for r in results if not isinstance(r, Exception)) == 1
        assert sum(1 for r in results if isinstance(r, ServiceError) and r.code == "astrologer_busy") == 1
        spent = (20_000 - await balance(a.uid)) + (20_000 - await balance(b.uid))
        assert spent == RATE                                              # only the winner was charged

    async def test_a_user_cannot_open_two_consultations_at_once(self):
        client = await make_client()
        first, second = await make_astrologer(), await make_astrologer()
        results = await asyncio.gather(attempt(start(client, first)), attempt(start(client, second)))
        assert sum(1 for r in results if not isinstance(r, Exception)) == 1
        assert sum(1 for r in results if isinstance(r, ServiceError) and r.code == "already_in_session") == 1

    async def test_ending_and_billing_at_the_same_moment_charge_each_minute_once(self):
        client, astro = await make_client(), await make_astrologer()
        s = await start(client, astro)
        async with session_scope() as db:
            await consult.accept_session(db, astro.uid, s.id, now=T0)
        from datetime import timedelta

        later = T0 + timedelta(seconds=150)

        async def sweep():
            async with session_scope() as db:
                return await consult.sweep(db, now=later)

        async def end():
            async with session_scope() as db:
                return await consult.end_session(db, client.uid, s.id, now=later)

        await asyncio.gather(sweep(), end(), sweep(), end(), return_exceptions=True)
        async with session_scope() as db:
            from app.database.models import ConsultSession
            final = await db.get(ConsultSession, s.id)
        assert final.status == "ended" and final.billed_minutes == 3
        assert await balance(client.uid) == 20_000 - 3 * RATE + final.refunded_paise
