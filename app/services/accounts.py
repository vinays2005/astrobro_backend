"""Accounts, premium entitlements and per-user AI chat metering. The server is the source of truth for all three."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Account, Entitlement, UsageDaily, utcnow
from app.security.identity import AuthUser

IST = ZoneInfo("Asia/Kolkata")

# plan id -> (price in paise, days of premium). tests/test_billing.py pins this to the app's paywall and to the
# legacy /api/payment/create-order prices, so the three can never drift apart.
PLANS: dict[str, tuple[int, int]] = {
    "weekly": (4900, 7),
    "monthly": (14900, 30),
    "quarterly": (39900, 90),
    "yearly": (99900, 365),
}


def today_ist() -> date:
    """The free allowance resets at midnight India time."""
    return datetime.now(IST).date()


async def ensure_account(db: AsyncSession, user: AuthUser) -> Account:
    """Create the account row on first use and keep its details fresh. Call before anything that spends or stores."""
    acct = await db.get(Account, user.uid)
    if acct is None:
        acct = Account(uid=user.uid, email=user.email, display_name=user.name)
        db.add(acct)
        try:
            await db.flush()
        except IntegrityError:               # two first requests raced; the other one created it
            await db.rollback()
            acct = await db.get(Account, user.uid)
    else:
        if user.email and acct.email != user.email:
            acct.email = user.email
        if user.name and acct.display_name != user.name:
            acct.display_name = user.name
        acct.last_seen_at = utcnow()
    return acct


# ── Premium ───────────────────────────────────────────────────────────────────

async def premium_until(db: AsyncSession, uid: str, now: datetime | None = None) -> datetime | None:
    ent = await db.get(Entitlement, uid)
    now = now or utcnow()
    return ent.valid_until if ent and ent.valid_until > now else None


async def is_premium(db: AsyncSession, uid: str, now: datetime | None = None) -> bool:
    return await premium_until(db, uid, now) is not None


async def grant_premium(db: AsyncSession, uid: str, days: int, now: datetime | None = None) -> datetime:
    """Extend premium by `days`, counted from the current expiry when it is still running (no time is lost)."""
    now = now or utcnow()
    ent = await db.get(Entitlement, uid, with_for_update=True)
    base = ent.valid_until if ent is not None and ent.valid_until > now else now
    until = base + timedelta(days=days)
    if ent is None:
        db.add(Entitlement(uid=uid, valid_until=until, updated_at=now))
    else:
        ent.valid_until = until
        ent.updated_at = now
    await db.flush()
    return until


# ── Daily AI chat allowance ───────────────────────────────────────────────────

async def chat_limit(db: AsyncSession, uid: str) -> int:
    s = get_settings()
    return s.premium_chats_per_day if await is_premium(db, uid) else s.free_chats_per_day


async def usage_today(db: AsyncSession, uid: str) -> int:
    row = await db.get(UsageDaily, (uid, today_ist()))
    return row.chats if row else 0


async def consume_chat(db: AsyncSession, uid: str) -> tuple[bool, int, int]:
    """Use one chat from today's allowance. Returns (allowed, chats used today, daily limit)."""
    limit = await chat_limit(db, uid)
    day = today_ist()
    row = await db.get(UsageDaily, (uid, day), with_for_update=True)
    if row is None:
        row = UsageDaily(uid=uid, day=day, chats=0)
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            row = await db.get(UsageDaily, (uid, day), with_for_update=True)
    if row.chats >= limit:
        return False, row.chats, limit
    row.chats += 1
    await db.flush()
    return True, row.chats, limit


async def release_chat(db: AsyncSession, uid: str) -> None:
    """Give a chat back when the AI failed, so an outage never costs the user their allowance."""
    row = await db.get(UsageDaily, (uid, today_ist()), with_for_update=True)
    if row is not None and row.chats > 0:
        row.chats -= 1
        await db.flush()
