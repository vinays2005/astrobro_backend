"""Deleting an account: erase the person's data (Digital Personal Data Protection Act, 2023), keep only what a law requires.

Erased: AI memory notes, usage counts, the plan, legacy saved charts and chats, the topics and birth details shared in
consultations, the messages of those consultations, booking contact details, review comments, report details that are
no longer needed, an astrologer's public profile and payout UPI, and the account's email and name.

Kept, because a law requires it: payment, wallet and earnings ledgers (tax and accounting law), the messages of a
consultation with an open abuse report (until it is reviewed), and the uid + email in account_deletions for 180 days
(Rule 3(1)(h) of the IT Intermediary Rules, 2021), removed afterwards by purge_expired.

Deletion is refused while money or a service is still in flight, so nobody loses a wallet balance, unpaid earnings or
a paid booking by deleting their account.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (AbuseReport, Account, AccountDeletion, Astrologer, Booking, Chat, ChatMemory,
                                 ConsultMessage, ConsultSession, Entitlement, Kundli, Review, UsageDaily, User, utcnow)
from app.services import wallet
from app.services.errors import ServiceError

REGISTRATION_RETENTION = timedelta(days=180)
_NO_SYNC = {"synchronize_session": False}


async def _count(db: AsyncSession, query) -> int:
    return (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()


async def _refuse_if_busy(db: AsyncSession, uid: str) -> None:
    balance = await wallet.balance(db, uid)
    if balance > 0:
        raise ServiceError("Your wallet still has money in it. Use it, or ask support to refund it, before you delete "
                           "your account.", status=409, code="wallet_not_empty", balance_paise=balance)
    if await _count(db, select(ConsultSession.id).where(
            (ConsultSession.user_uid == uid) | (ConsultSession.astrologer_uid == uid),
            ConsultSession.status.in_(("requested", "active")))):
        raise ServiceError("Finish your consultation before you delete your account.", status=409,
                           code="consult_in_progress")
    if await _count(db, select(Booking.id).where(Booking.user_uid == uid, Booking.status.in_(("paid", "confirmed")))):
        raise ServiceError("You have a paid booking that is not finished. Cancel it, or wait until it is completed, "
                           "before you delete your account.", status=409, code="booking_in_progress")
    astrologer = await db.get(Astrologer, uid)
    if astrologer is not None and astrologer.earnings_paise > 0:
        raise ServiceError("You have unpaid earnings. Ask support for your payout before you delete your account.",
                           status=409, code="earnings_unpaid", earnings_paise=astrologer.earnings_paise)


async def delete_account(db: AsyncSession, uid: str, email: str | None = None, now: datetime | None = None) -> dict:
    """Erase everything about `uid` that no law requires us to keep. Safe to call again (it is idempotent)."""
    now = now or utcnow()
    await _refuse_if_busy(db, uid)

    for model in (ChatMemory, UsageDaily, Entitlement):
        await db.execute(delete(model).where(model.uid == uid).execution_options(**_NO_SYNC))

    # Saved charts and chats from the original (pre-Firebase) tables.
    legacy_users = select(User.id).where(User.firebase_uid == uid)
    kundlis = select(Kundli.id).where(Kundli.user_id.in_(legacy_users))
    await db.execute(delete(Chat).where(Chat.kundli_id.in_(kundlis)).execution_options(**_NO_SYNC))
    await db.execute(delete(Kundli).where(Kundli.user_id.in_(legacy_users)).execution_options(**_NO_SYNC))
    await db.execute(delete(User).where(User.firebase_uid == uid).execution_options(**_NO_SYNC))

    # Consultations they booked: the billing rows stay (money), what was said and shared goes.
    own_sessions = select(ConsultSession.id).where(ConsultSession.user_uid == uid)
    disputed = select(AbuseReport.session_id).where(AbuseReport.status == "open", AbuseReport.session_id.is_not(None))
    await db.execute(delete(ConsultMessage).where(ConsultMessage.session_id.in_(own_sessions),
                                                  ConsultMessage.session_id.not_in(disputed))
                     .execution_options(**_NO_SYNC))
    await db.execute(update(ConsultSession).where(ConsultSession.user_uid == uid)
                     .values(topic=None, birth_snapshot=None).execution_options(**_NO_SYNC))

    await db.execute(update(Booking).where(Booking.user_uid == uid, Booking.status == "pending_payment")
                     .values(status="cancelled").execution_options(**_NO_SYNC))
    await db.execute(update(Booking).where(Booking.user_uid == uid)
                     .values(contact_name="", contact_phone="", location_text=None, notes=None, updated_at=now)
                     .execution_options(**_NO_SYNC))
    await db.execute(update(Review).where(Review.user_uid == uid).values(comment=None).execution_options(**_NO_SYNC))
    await db.execute(update(AbuseReport).where(AbuseReport.reporter_uid == uid, AbuseReport.status != "open")
                     .values(details=None).execution_options(**_NO_SYNC))

    astrologer = await db.get(Astrologer, uid, with_for_update=True)
    if astrologer is not None:
        # The row stays so past consultations still show who they were with, but nothing identifies the person.
        astrologer.name = "Former astrologer"
        astrologer.bio = ""
        astrologer.photo_url = None
        astrologer.payout_upi = None
        astrologer.is_online = False
        astrologer.status = "suspended"
        astrologer.status_note = "Account deleted"

    account = await db.get(Account, uid, with_for_update=True)
    if account is not None:
        email = email or account.email
        account.email = None
        account.display_name = None

    if await db.get(AccountDeletion, uid) is None:
        db.add(AccountDeletion(uid=uid, email=email, deleted_at=now))
    await db.flush()
    return {"deleted": True, "registration_kept_days": REGISTRATION_RETENTION.days}


async def purge_expired(db: AsyncSession, now: datetime | None = None) -> int:
    """Remove the registration details of accounts deleted more than 180 days ago."""
    now = now or utcnow()
    result = await db.execute(delete(AccountDeletion).where(AccountDeletion.deleted_at < now - REGISTRATION_RETENTION)
                              .execution_options(**_NO_SYNC))
    return result.rowcount or 0
