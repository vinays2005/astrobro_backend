"""Owner tools: money summary, payouts to astrologers, wallet corrections, blocking, abuse reports."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (AbuseReport, Account, Astrologer, Booking, ConsultSession, EarningsEntry, Entitlement,
                                 Payment, Wallet, WalletEntry, utcnow)
from app.services import astrologers, wallet
from app.services.errors import ServiceError


async def _sum(db: AsyncSession, column, *conditions) -> int:
    return int((await db.execute(select(func.coalesce(func.sum(column), 0)).where(*conditions))).scalar_one())


async def _count(db: AsyncSession, model, *conditions) -> int:
    return int((await db.execute(select(func.count()).select_from(model).where(*conditions))).scalar_one())


async def summary(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or utcnow()
    day_ago = now - timedelta(days=1)
    kept = ConsultSession.refunded_paise == 0                         # a refunded chat earned nobody anything
    net_charges = await _sum(db, ConsultSession.charged_paise, kept)
    commission = await _sum(db, ConsultSession.charged_paise - ConsultSession.astrologer_earned_paise, kept)
    return {
        "accounts": await _count(db, Account),
        "premium_now": await _count(db, Entitlement, Entitlement.valid_until > now),
        "astrologers": {s: await _count(db, Astrologer, Astrologer.status == s)
                        for s in ("pending", "approved", "rejected", "suspended")},
        "consultations": {
            "total": await _count(db, ConsultSession), "active": await _count(db, ConsultSession, ConsultSession.status == "active"),
            "last_24h": await _count(db, ConsultSession, ConsultSession.created_at >= day_ago),
        },
        "money_paise": {
            "plan_sales": await _sum(db, Payment.amount_paise, Payment.purpose == "plan", Payment.status == "paid"),
            "report_sales": await _sum(db, Payment.amount_paise, Payment.purpose == "report", Payment.status == "paid"),
            "wallet_topups": await _sum(db, Payment.amount_paise, Payment.purpose == "wallet", Payment.status == "paid"),
            "booking_sales": await _sum(db, Payment.amount_paise, Payment.purpose == "booking", Payment.status == "paid"),
            "consultation_charges": net_charges,
            "platform_commission": commission,
            "owed_to_astrologers": await _sum(db, Astrologer.earnings_paise),
            "user_wallet_balances": await _sum(db, Wallet.balance_paise),
        },
        "bookings": {s: await _count(db, Booking, Booking.status == s)
                     for s in ("paid", "confirmed", "completed", "refunded", "cancelled")},
        "open_reports": await _count(db, AbuseReport, AbuseReport.status == "open"),
    }


async def pending_astrologers(db: AsyncSession, status: str = "pending") -> list[dict]:
    rows = (await db.execute(select(Astrologer).where(Astrologer.status == status).order_by(Astrologer.created_at))).scalars().all()
    return [{**astrologers.own_profile(a), "created_at": a.created_at.isoformat() + "Z"} for a in rows]


async def payout(db: AsyncSession, astrologer_uid: str, amount_paise: int, note: str | None) -> dict:
    """Record money the owner has sent to an astrologer (by UPI or bank transfer, outside the app)."""
    a = await astrologers.get(db, astrologer_uid, lock=True)
    if a is None:
        raise ServiceError("No such astrologer.", status=404, code="not_found")
    if amount_paise > a.earnings_paise:
        raise ServiceError(f"Only Rs {a.earnings_paise / 100:.2f} is owed to this astrologer.", status=409, code="too_much",
                           owed_paise=a.earnings_paise)
    a.earnings_paise -= amount_paise
    db.add(EarningsEntry(astrologer_uid=a.uid, kind="payout", amount_paise=-amount_paise, balance_after_paise=a.earnings_paise,
                         ref_type="admin", ref_id="payout-" + uuid.uuid4().hex, note=note or "Payout"))
    await db.flush()
    return {"astrologer_uid": a.uid, "paid_paise": amount_paise, "still_owed_paise": a.earnings_paise, "payout_upi": a.payout_upi}


async def adjust_wallet(db: AsyncSession, uid: str, amount_paise: int, note: str) -> dict:
    """A manual correction or goodwill credit. Positive adds money, negative takes it back (never below zero)."""
    if amount_paise == 0:
        raise ServiceError("The amount cannot be zero.", code="zero")
    ref = "adjust-" + uuid.uuid4().hex
    if amount_paise > 0:
        await wallet.credit(db, uid, amount_paise, "adjustment", "admin", ref, note=note)
    elif await wallet.debit(db, uid, -amount_paise, "adjustment", "admin", ref, note=note) == wallet.INSUFFICIENT:
        raise ServiceError("That is more than the wallet holds.", status=409, code="insufficient_balance")
    return {"uid": uid, "balance_paise": await wallet.balance(db, uid)}


async def set_blocked(db: AsyncSession, uid: str, blocked: bool) -> dict:
    acct = await db.get(Account, uid, with_for_update=True)
    if acct is None:
        raise ServiceError("No such account.", status=404, code="not_found")
    acct.is_blocked = blocked
    return {"uid": uid, "blocked": blocked}


async def open_reports(db: AsyncSession, status: str = "open", limit: int = 100) -> list[dict]:
    rows = (await db.execute(select(AbuseReport).where(AbuseReport.status == status)
                             .order_by(AbuseReport.id.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "reporter_uid": r.reporter_uid, "target_uid": r.target_uid, "session_id": r.session_id,
             "reason": r.reason, "details": r.details, "status": r.status, "created_at": r.created_at.isoformat() + "Z"}
            for r in rows]


async def resolve_report(db: AsyncSession, report_id: int) -> dict:
    report = await db.get(AbuseReport, report_id)
    if report is None:
        raise ServiceError("No such report.", status=404, code="not_found")
    report.status = "reviewed"
    return {"id": report.id, "status": report.status}


async def wallet_statement(db: AsyncSession, uid: str, limit: int = 50) -> dict:
    return {"uid": uid, "balance_paise": await wallet.balance(db, uid),
            "entries": [{"id": e.id, "kind": e.kind, "amount_paise": e.amount_paise, "balance_after_paise": e.balance_after_paise,
                         "note": e.note, "created_at": e.created_at.isoformat() + "Z"} for e in await wallet.history(db, uid, limit)]}
