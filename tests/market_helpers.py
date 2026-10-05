"""Shared setup for marketplace tests: people with wallets, approved online astrologers, and a controllable clock."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.database.connection import session_scope
from app.database.models import (Astrologer, ConsultMessage, ConsultSession, EarningsEntry, WalletEntry, utcnow)
from app.security.identity import AuthUser
from app.services import accounts, astrologers, consult, wallet

RATE = 1000                                  # Rs 10 a minute
T0 = utcnow().replace(microsecond=0)


def new_uid(prefix: str = "u") -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def person(uid: str | None = None, *, admin: bool = False) -> AuthUser:
    uid = uid or new_uid()
    return AuthUser(uid=uid, email=f"{uid}@example.com", email_verified=True, name=uid.title(), is_admin=admin)


def at(seconds: float = 0, minutes: float = 0):
    return T0 + timedelta(seconds=seconds, minutes=minutes)


async def fund(uid: str, paise: int) -> None:
    async with session_scope() as db:
        await wallet.credit(db, uid, paise, "topup", "payment", new_uid("pay"))


async def make_client(paise: int = 20_000, *, terms: bool = True) -> AuthUser:
    """A signed-in user with money in the wallet who has accepted the consultation terms."""
    user = person()
    async with session_scope() as db:
        await accounts.ensure_account(db, user)
        if terms:
            await accounts.accept_terms(db, user)
    if paise:
        await fund(user.uid, paise)
    return user


async def make_astrologer(*, chat: int | None = RATE, call: int | None = None, video: int | None = None,
                          approved: bool = True, online: bool = True, now=T0, languages=("Hindi", "English"),
                          specialties=("Marriage",), name: str = "Pandit Ji", experience: int = 5) -> AuthUser:
    user = person(new_uid("a"))
    async with session_scope() as db:
        await accounts.ensure_account(db, user)
        await astrologers.apply(db, user, {
            "name": name, "bio": "Vedic astrologer", "languages": list(languages), "specialties": list(specialties),
            "experience_years": experience, "chat_rate_paise": chat, "call_rate_paise": call, "video_rate_paise": video,
        })
    if approved:
        async with session_scope() as db:
            await astrologers.set_status(db, user.uid, "approved")
        if online:
            async with session_scope() as db:
                await astrologers.set_presence(db, user.uid, True, now)
    return user


async def balance(uid: str) -> int:
    async with session_scope() as db:
        return await wallet.balance(db, uid)


async def earnings(uid: str) -> int:
    async with session_scope() as db:
        return (await db.get(Astrologer, uid)).earnings_paise


async def get_session(session_id: str) -> ConsultSession:
    async with session_scope() as db:
        return await db.get(ConsultSession, session_id)


async def start(client: AuthUser, astro: AuthUser, mode: str = "chat", now=T0, **kw) -> ConsultSession:
    async with session_scope() as db:
        return await consult.start_session(db, client, astro.uid, mode, now=now, **kw)


async def start_and_accept(client: AuthUser, astro: AuthUser, mode: str = "chat", now=T0) -> ConsultSession:
    s = await start(client, astro, mode, now=now)
    async with session_scope() as db:
        return await consult.accept_session(db, astro.uid, s.id, now=now)


async def bill(session_id: str, now) -> ConsultSession:
    async with session_scope() as db:
        s = await db.get(ConsultSession, session_id)
        await consult.bill_due_minutes(db, s, now)
        return s


async def end(uid: str, session_id: str, now) -> ConsultSession:
    async with session_scope() as db:
        return await consult.end_session(db, uid, session_id, now=now)


async def say(uid: str, session_id: str, text: str, now=T0) -> ConsultMessage:
    async with session_scope() as db:
        return await consult.send_message(db, uid, session_id, text, now=now)


async def ledger_totals(session_id: str) -> dict:
    """What the books say about one session: wallet debits, refunds, astrologer credits."""
    async with session_scope() as db:
        wallet_rows = (await db.execute(select(WalletEntry).where(WalletEntry.ref_id.like(f"{session_id}%")))).scalars().all()
        wallet_rows += (await db.execute(select(WalletEntry).where(WalletEntry.ref_id == session_id))).scalars().all()
        earn_rows = (await db.execute(select(EarningsEntry).where(EarningsEntry.ref_id.like(f"{session_id}%")))).scalars().all()
    seen = {e.id: e for e in wallet_rows}
    return {
        "charged": -sum(e.amount_paise for e in seen.values() if e.kind == "consult_charge"),
        "refunded": sum(e.amount_paise for e in seen.values() if e.kind == "refund"),
        "earned": sum(e.amount_paise for e in earn_rows),
    }
