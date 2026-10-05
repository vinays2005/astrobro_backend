"""Consultations with human astrologers: requests, minute-by-minute billing, messages, reviews.

Money rules. Everything below runs inside one database transaction, locking rows in a fixed order (session, then
the astrologer, then the user's wallet) so two things can never deadlock, and every check happens BEFORE any money
moves, so a refusal never leaves a half-finished charge behind:

- a minute is charged to the user's wallet when it STARTS; minute 1 is charged when the astrologer accepts
- the astrologer earns the charge minus the platform commission, recorded in their own ledger
- a session ends when either side ends it, when the wallet cannot pay the next minute, after sitting idle, after
  the maximum length, or when the astrologer stops checking in
- a chat the astrologer never answered is refunded in full
- every ledger row has a unique reference (session id + minute), so repeating a step never charges twice
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import (AbuseReport, Astrologer, ConsultMessage, ConsultSession, EarningsEntry, Review, utcnow)
from app.security.identity import AuthUser
from app.services import accounts, astrologers, wallet
from app.services.errors import ServiceError
from app.services.moderation import contact_info_reason
from app.services.waiters import waiters

MAX_SESSION_MINUTES = 180
ASTROLOGER_SILENCE_SECONDS = 180          # an active session whose astrologer has not checked in this long is ended
MESSAGE_MAX_CHARS = 2000
ABUSE_REASONS = ("abuse", "inappropriate", "fraud", "spam", "other")
JITSI_BASE = "https://meet.jit.si/"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def session_key(session_id: str) -> str:
    return f"session:{session_id}"


def inbox_key(astrologer_uid: str) -> str:
    return f"inbox:{astrologer_uid}"


def effective_status(s: ConsultSession, now: datetime) -> str:
    """A request nobody answered in time is expired even before the sweeper has written that down."""
    if s.status == "requested" and now - s.created_at > timedelta(seconds=get_settings().consult_request_ttl_seconds):
        return "expired"
    return s.status


def role_in(s: ConsultSession, uid: str) -> str | None:
    if uid == s.user_uid:
        return "user"
    if uid == s.astrologer_uid:
        return "astrologer"
    return None


def session_view(s: ConsultSession, role: str, now: datetime) -> dict:
    """A session as one of its two participants may see it."""
    paid_until = s.accepted_at + timedelta(minutes=s.billed_minutes) if s.accepted_at and s.billed_minutes else None
    view = {
        "id": s.id, "mode": s.mode, "status": effective_status(s, now), "role": role,
        "astrologer_uid": s.astrologer_uid, "rate_paise_per_min": s.rate_paise_per_min, "topic": s.topic,
        "created_at": _iso(s.created_at), "accepted_at": _iso(s.accepted_at), "ended_at": _iso(s.ended_at),
        "ended_by": s.ended_by, "end_reason": s.end_reason, "billed_minutes": s.billed_minutes,
        "charged_paise": s.charged_paise, "refunded_paise": s.refunded_paise, "paid_until": _iso(paid_until),
        "join_url": JITSI_BASE + s.room if s.room and s.status == "active" else None,
    }
    if role == "astrologer":
        view["user_uid"] = s.user_uid
        view["birth_data"] = s.birth_snapshot
        view["earned_paise"] = s.astrologer_earned_paise
    return view


async def _locked_session(db: AsyncSession, session_id: str) -> ConsultSession:
    s = await db.get(ConsultSession, session_id, with_for_update=True)
    if s is None:
        raise ServiceError("Consultation not found.", status=404, code="not_found")
    return s


async def _participant_session(db: AsyncSession, uid: str, session_id: str, *, lock: bool = False) -> tuple[ConsultSession, str]:
    s = await (_locked_session(db, session_id) if lock else db.get(ConsultSession, session_id))
    role = role_in(s, uid) if s else None
    if s is None or role is None:
        raise ServiceError("Consultation not found.", status=404, code="not_found")     # same answer for strangers
    return s, role


async def _system_message(db: AsyncSession, s: ConsultSession, text: str, now: datetime) -> None:
    db.add(ConsultMessage(session_id=s.id, sender_uid="system", body=text, kind="system", created_at=now))


# ── Requesting and answering ──────────────────────────────────────────────────

async def start_session(db: AsyncSession, user: AuthUser, astrologer_uid: str, mode: str, topic: str | None = None,
                        birth_data: dict | None = None, now: datetime | None = None) -> ConsultSession:
    now = now or utcnow()
    s = get_settings()
    if mode not in astrologers.MODES:
        raise ServiceError("mode must be chat, call or video.", code="bad_mode")
    if user.uid == astrologer_uid:
        raise ServiceError("You cannot consult yourself.", code="self_consult")
    acct = await accounts.ensure_account(db, user)
    if acct.is_blocked:
        raise ServiceError("Your account has been suspended. Contact support.", status=403, code="blocked")
    if acct.terms_accepted_at is None:
        raise ServiceError("Please accept the consultation terms (18+ only) first.", status=428, code="terms_required")

    a = await astrologers.get(db, astrologer_uid)
    if a is None or a.status != "approved":
        raise ServiceError("This astrologer is not available.", status=404, code="not_found")
    rate = astrologers.rate_for(a, mode)
    if rate is None:
        raise ServiceError(f"This astrologer does not offer {mode} consultations.", code="mode_not_offered")
    if not astrologers.is_online(a, now):
        raise ServiceError("This astrologer is offline right now.", status=409, code="astrologer_offline")

    await wallet.lock(db, user.uid)                                    # serialises this user's own requests
    open_count = (await db.execute(select(func.count()).select_from(ConsultSession).where(
        ConsultSession.user_uid == user.uid, ConsultSession.status.in_(("requested", "active"))))).scalar_one()
    if open_count:
        # A request nobody answered is as good as expired; do not let it block the user.
        stale = (await db.execute(select(ConsultSession).where(
            ConsultSession.user_uid == user.uid, ConsultSession.status == "requested"))).scalars().all()
        for old in stale:
            if effective_status(old, now) == "expired":
                old.status, old.ended_at, old.ended_by, old.end_reason = "expired", now, "system", "expired"
        still_open = (await db.execute(select(func.count()).select_from(ConsultSession).where(
            ConsultSession.user_uid == user.uid, ConsultSession.status.in_(("requested", "active"))))).scalar_one()
        if still_open:
            raise ServiceError("You already have a consultation in progress.", status=409, code="already_in_session")

    needed = rate * s.consult_min_minutes
    balance = await wallet.balance(db, user.uid)
    if balance < needed:
        raise ServiceError(f"Add money to your wallet first: you need at least Rs {needed / 100:.0f} for a "
                           f"{s.consult_min_minutes}-minute {mode}.", status=402, code="insufficient_balance",
                           needed_paise=needed, balance_paise=balance)

    session = ConsultSession(user_uid=user.uid, astrologer_uid=astrologer_uid, mode=mode, status="requested",
                             rate_paise_per_min=rate, commission_percent=s.platform_commission_percent,
                             topic=(topic or "").strip()[:200] or None, birth_snapshot=birth_data, created_at=now,
                             last_activity_at=now)
    db.add(session)
    await db.flush()
    waiters.notify_after_commit(db, inbox_key(astrologer_uid))
    return session


async def _credit_astrologer(db: AsyncSession, uid: str, amount: int, kind: str, ref_id: str, note: str | None = None) -> None:
    """Add to (or, for a reversal, take from) the astrologer's earnings, once per reference."""
    already = (await db.execute(select(EarningsEntry.id).where(
        EarningsEntry.kind == kind, EarningsEntry.ref_type == "session", EarningsEntry.ref_id == ref_id))).first()
    if already:
        return
    a = await astrologers.get(db, uid, lock=True)
    a.earnings_paise += amount
    db.add(EarningsEntry(astrologer_uid=uid, kind=kind, amount_paise=amount, balance_after_paise=a.earnings_paise,
                         ref_type="session", ref_id=ref_id, note=note))


async def _charge_minute(db: AsyncSession, s: ConsultSession, minute: int) -> str:
    """Charge one minute. Returns "ok", "duplicate" (already charged) or "insufficient"."""
    await astrologers.get(db, s.astrologer_uid, lock=True)            # lock order: astrologer before wallet
    outcome = await wallet.debit(db, s.user_uid, s.rate_paise_per_min, "consult_charge", "session", f"{s.id}:{minute}",
                                 note=f"{s.mode.capitalize()} consultation, minute {minute}")
    if outcome == wallet.INSUFFICIENT:
        return "insufficient"
    earned = s.rate_paise_per_min * (100 - s.commission_percent) // 100
    if outcome == wallet.APPLIED:
        await _credit_astrologer(db, s.astrologer_uid, earned, "consult", f"{s.id}:{minute}",
                                 note=f"{s.mode.capitalize()} consultation, minute {minute}")
        s.charged_paise += s.rate_paise_per_min
        s.astrologer_earned_paise += earned
    s.billed_minutes = max(s.billed_minutes, minute)
    return "ok" if outcome == wallet.APPLIED else "duplicate"


async def accept_session(db: AsyncSession, astrologer_uid: str, session_id: str, now: datetime | None = None) -> ConsultSession:
    """The astrologer takes a request. Charges minute 1; a user who can no longer pay gets a declined session."""
    now = now or utcnow()
    s = await _locked_session(db, session_id)
    if s.astrologer_uid != astrologer_uid:
        raise ServiceError("Consultation not found.", status=404, code="not_found")
    if effective_status(s, now) == "expired":
        raise ServiceError("This request has expired.", status=410, code="expired")
    if s.status != "requested":
        raise ServiceError("This request is no longer waiting.", status=409, code="not_pending")

    a = await astrologers.get(db, astrologer_uid, lock=True)
    if a is None or a.status != "approved":
        raise ServiceError("Only approved astrologers can take consultations.", status=403, code="not_approved")
    busy = (await db.execute(select(func.count()).select_from(ConsultSession).where(
        ConsultSession.astrologer_uid == astrologer_uid, ConsultSession.status == "active",
        ConsultSession.id != s.id))).scalar_one()
    if busy:
        raise ServiceError("Finish your current consultation first.", status=409, code="astrologer_busy")

    if await _charge_minute(db, s, 1) == "insufficient":
        s.status, s.ended_at, s.ended_by, s.end_reason = "declined", now, "system", "insufficient_balance"
        waiters.notify_after_commit(db, session_key(s.id))
        return s

    s.status, s.accepted_at, s.last_activity_at = "active", now, now
    if s.mode in ("call", "video"):
        s.room = f"astrobro-{s.id[:8]}-{secrets.token_urlsafe(9)}"
    await _system_message(db, s, "Consultation started. Please keep the conversation respectful.", now)
    waiters.notify_after_commit(db, session_key(s.id))
    return s


async def decline_session(db: AsyncSession, astrologer_uid: str, session_id: str, now: datetime | None = None) -> ConsultSession:
    now = now or utcnow()
    s = await _locked_session(db, session_id)
    if s.astrologer_uid != astrologer_uid:
        raise ServiceError("Consultation not found.", status=404, code="not_found")
    if s.status != "requested":
        raise ServiceError("This request is no longer waiting.", status=409, code="not_pending")
    s.status, s.ended_at, s.ended_by, s.end_reason = "declined", now, "astrologer", "declined"
    waiters.notify_after_commit(db, session_key(s.id))
    return s


async def cancel_request(db: AsyncSession, user_uid: str, session_id: str, now: datetime | None = None) -> ConsultSession:
    now = now or utcnow()
    s = await _locked_session(db, session_id)
    if s.user_uid != user_uid:
        raise ServiceError("Consultation not found.", status=404, code="not_found")
    if s.status != "requested":
        raise ServiceError("Only a waiting request can be cancelled.", status=409, code="not_pending")
    s.status, s.ended_at, s.ended_by, s.end_reason = "cancelled", now, "user", "cancelled"
    waiters.notify_after_commit(db, inbox_key(s.astrologer_uid))
    waiters.notify_after_commit(db, session_key(s.id))
    return s


# ── Billing and ending ────────────────────────────────────────────────────────

async def _finish(db: AsyncSession, s: ConsultSession, ended_by: str, reason: str, now: datetime) -> None:
    await astrologers.get(db, s.astrologer_uid, lock=True)            # lock order: astrologer before wallet
    s.status, s.ended_at, s.ended_by, s.end_reason = "ended", now, ended_by, reason
    answered = (await db.execute(select(func.count()).select_from(ConsultMessage).where(
        ConsultMessage.session_id == s.id, ConsultMessage.sender_uid == s.astrologer_uid))).scalar_one()
    if s.mode == "chat" and s.charged_paise > 0 and answered == 0 and not s.refunded_paise:
        await wallet.credit(db, s.user_uid, s.charged_paise, "refund", "session", s.id, note="Chat not answered: refunded")
        await _credit_astrologer(db, s.astrologer_uid, -s.astrologer_earned_paise, "adjustment", f"{s.id}:refund",
                                 note="Refunded chat")
        s.refunded_paise = s.charged_paise
        await _system_message(db, s, "The astrologer did not reply, so this consultation was refunded.", now)
    a = await astrologers.get(db, s.astrologer_uid, lock=True)
    if a is not None:
        a.sessions_count += 1
        a.minutes_total += s.billed_minutes
    await _system_message(db, s, "Consultation ended.", now)
    waiters.notify_after_commit(db, session_key(s.id))
    waiters.notify_after_commit(db, inbox_key(s.astrologer_uid))


async def bill_due_minutes(db: AsyncSession, s: ConsultSession, now: datetime) -> None:
    """Catch the bill up to `now`: charge every minute that has started, and end the session if it cannot be paid."""
    if s.status != "active" or s.accepted_at is None:
        return
    elapsed = now - s.accepted_at
    due = min(int(elapsed.total_seconds() // 60) + 1, MAX_SESSION_MINUTES)
    while s.billed_minutes < due:
        if await _charge_minute(db, s, s.billed_minutes + 1) == "insufficient":
            paid_until = s.accepted_at + timedelta(minutes=s.billed_minutes)
            await _finish(db, s, "system", "insufficient_balance", min(now, paid_until))
            return
    if elapsed >= timedelta(minutes=MAX_SESSION_MINUTES):         # every minute up to the cap was charged first
        await _finish(db, s, "system", "max_duration", s.accepted_at + timedelta(minutes=MAX_SESSION_MINUTES))


async def end_session(db: AsyncSession, uid: str, session_id: str, now: datetime | None = None) -> ConsultSession:
    now = now or utcnow()
    s, role = await _participant_session(db, uid, session_id, lock=True)
    if s.status == "requested":
        return await (cancel_request(db, uid, session_id, now) if role == "user" else decline_session(db, uid, session_id, now))
    if s.status != "active":
        return s                                                       # already over: ending twice is harmless
    await bill_due_minutes(db, s, now)
    if s.status == "active":
        await _finish(db, s, role, "completed", now)
    return s


async def sweep(db: AsyncSession, now: datetime | None = None) -> dict:
    """Housekeeping run every few seconds: expire old requests, bill running sessions, end dead ones."""
    now = now or utcnow()
    settings = get_settings()
    counts = {"expired": 0, "ended": 0, "offline": 0}

    cutoff = now - timedelta(seconds=settings.consult_request_ttl_seconds)
    stale = (await db.execute(select(ConsultSession).where(
        ConsultSession.status == "requested", ConsultSession.created_at < cutoff).with_for_update())).scalars().all()
    for s in stale:
        s.status, s.ended_at, s.ended_by, s.end_reason = "expired", now, "system", "expired"
        waiters.notify_after_commit(db, inbox_key(s.astrologer_uid))
        waiters.notify_after_commit(db, session_key(s.id))
        counts["expired"] += 1

    active_ids = (await db.execute(select(ConsultSession.id).where(ConsultSession.status == "active"))).scalars().all()
    for session_id in active_ids:
        s = await _locked_session(db, session_id)
        await bill_due_minutes(db, s, now)
        if s.status == "active":
            a = await astrologers.get(db, s.astrologer_uid)
            silent = a is None or a.last_seen_at is None or now - a.last_seen_at > timedelta(seconds=ASTROLOGER_SILENCE_SECONDS)
            idle = s.mode == "chat" and now - s.last_activity_at > timedelta(seconds=settings.consult_idle_timeout_seconds)
            if silent or idle:
                await _finish(db, s, "system", "astrologer_offline" if silent else "idle", now)
        if s.status == "ended":
            counts["ended"] += 1

    gone = await db.execute(update(Astrologer).where(
        Astrologer.is_online.is_(True), Astrologer.last_seen_at < now - timedelta(seconds=astrologers.PRESENCE_TTL_SECONDS))
        .values(is_online=False).execution_options(synchronize_session=False))
    counts["offline"] = gone.rowcount or 0
    return counts


# ── Messages ──────────────────────────────────────────────────────────────────

def message_view(m: ConsultMessage) -> dict:
    return {"id": m.id, "sender": m.sender_uid, "kind": m.kind, "body": m.body, "created_at": _iso(m.created_at)}


async def send_message(db: AsyncSession, uid: str, session_id: str, body: str, now: datetime | None = None) -> ConsultMessage:
    now = now or utcnow()
    s, role = await _participant_session(db, uid, session_id, lock=True)
    text = (body or "").strip()
    if not text:
        raise ServiceError("Write a message first.", code="empty_message")
    if len(text) > MESSAGE_MAX_CHARS:
        raise ServiceError(f"Messages can be up to {MESSAGE_MAX_CHARS} characters.", code="too_long")
    await bill_due_minutes(db, s, now)                                 # a session out of money must not keep chatting
    if s.status != "active":
        raise ServiceError("This consultation is not active.", status=409, code="session_ended")
    if s.mode != "chat":
        raise ServiceError("Chat messages are only for chat consultations.", status=409, code="not_a_chat")
    if get_settings().block_contact_sharing:
        found = contact_info_reason(text)
        if found:
            raise ServiceError(f"For everyone's safety, please do not share {found} here.", status=422, code="contact_blocked")
    msg = ConsultMessage(session_id=s.id, sender_uid=uid, body=text, kind="text", created_at=now)
    db.add(msg)
    s.last_activity_at = now
    await db.flush()
    waiters.notify_after_commit(db, session_key(s.id))
    return msg


async def messages_after(db: AsyncSession, uid: str, session_id: str, after_id: int = 0, limit: int = 100,
                         now: datetime | None = None) -> tuple[list[dict], dict]:
    """New messages plus the session's current state (so a poll also learns that the session ended).

    An astrologer reading their open chat is present, so the poll also keeps their presence fresh: a consultation
    must not be ended as abandoned just because they are in the room and not on the dashboard."""
    now = now or utcnow()
    s, role = await _participant_session(db, uid, session_id)
    if role == "astrologer" and s.status == "active":
        await astrologers.touch(db, uid, now, even_if_offline=True)
    rows = (await db.execute(select(ConsultMessage).where(
        ConsultMessage.session_id == session_id, ConsultMessage.id > after_id)
        .order_by(ConsultMessage.id).limit(limit))).scalars().all()
    return [message_view(m) for m in rows], session_view(s, role, now)


# ── Lists, reviews, reports ───────────────────────────────────────────────────

async def my_sessions(db: AsyncSession, uid: str, role: str = "user", limit: int = 30) -> list[dict]:
    now = utcnow()
    column = ConsultSession.user_uid if role == "user" else ConsultSession.astrologer_uid
    rows = (await db.execute(select(ConsultSession).where(column == uid)
                             .order_by(ConsultSession.created_at.desc()).limit(limit))).scalars().all()
    return [session_view(s, role, now) for s in rows]


async def astrologer_inbox(db: AsyncSession, uid: str, now: datetime | None = None) -> dict:
    """What an astrologer needs on the dashboard: waiting requests and the consultation in progress."""
    now = now or utcnow()
    cutoff = now - timedelta(seconds=get_settings().consult_request_ttl_seconds)
    waiting = (await db.execute(select(ConsultSession).where(
        ConsultSession.astrologer_uid == uid, ConsultSession.status == "requested", ConsultSession.created_at >= cutoff)
        .order_by(ConsultSession.created_at))).scalars().all()
    active = (await db.execute(select(ConsultSession).where(
        ConsultSession.astrologer_uid == uid, ConsultSession.status == "active"))).scalars().first()
    return {"requests": [session_view(s, "astrologer", now) for s in waiting],
            "active": session_view(active, "astrologer", now) if active else None}


async def add_review(db: AsyncSession, uid: str, session_id: str, rating: int, comment: str | None) -> Review:
    s, role = await _participant_session(db, uid, session_id)
    if role != "user":
        raise ServiceError("Only the person who consulted can leave a review.", status=403, code="not_the_client")
    if s.status != "ended" or s.billed_minutes < 1 or s.refunded_paise:
        raise ServiceError("You can review a consultation after it has finished.", status=409, code="not_reviewable")
    if not 1 <= rating <= 5:
        raise ServiceError("The rating must be from 1 to 5.", code="bad_rating")
    text = (comment or "").strip()[:500] or None
    if text and get_settings().block_contact_sharing and contact_info_reason(text):
        raise ServiceError("Please do not put contact details in a review.", status=422, code="contact_blocked")
    if (await db.execute(select(Review.id).where(Review.session_id == session_id))).first():
        raise ServiceError("You have already reviewed this consultation.", status=409, code="already_reviewed")
    review = Review(session_id=session_id, user_uid=uid, astrologer_uid=s.astrologer_uid, rating=rating, comment=text)
    db.add(review)
    a = await astrologers.get(db, s.astrologer_uid, lock=True)
    a.rating_avg = (a.rating_avg * a.rating_count + rating) / (a.rating_count + 1)
    a.rating_count += 1
    await db.flush()
    return review


async def report_abuse(db: AsyncSession, uid: str, session_id: str, reason: str, details: str | None) -> AbuseReport:
    s, role = await _participant_session(db, uid, session_id)
    if reason not in ABUSE_REASONS:
        raise ServiceError(f"reason must be one of: {', '.join(ABUSE_REASONS)}", code="bad_reason")
    target = s.astrologer_uid if role == "user" else s.user_uid
    report = AbuseReport(reporter_uid=uid, target_uid=target, session_id=session_id, reason=reason,
                         details=(details or "").strip()[:500] or None)
    db.add(report)
    await db.flush()
    return report
