"""Pandit and puja bookings: a catalogue the admin manages, paid through Razorpay, fulfilled by the admin.

A booking is created unpaid, paid through the normal /api/billing flow (purpose "booking"), then confirmed and
completed by the admin, who assigns a pandit. A cancellation before confirmation, or a refund, goes back to the
user's wallet in full.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Booking, Payment, ServiceItem, utcnow
from app.security.identity import AuthUser
from app.services import accounts, billing, wallet
from app.services.errors import ServiceError

IST = ZoneInfo("Asia/Kolkata")
MIN_LEAD_HOURS = 4
MAX_ADVANCE_DAYS = 120
_PHONE = re.compile(r"^\+?\d[\d\s-]{8,16}\d$")
# status -> statuses the admin may move it to
_ADMIN_MOVES = {
    "confirmed": {"paid"},
    "completed": {"confirmed"},
    "refunded": {"paid", "confirmed", "completed"},
    "cancelled": {"pending_payment"},
}


def service_view(s: ServiceItem) -> dict:
    return {"id": s.id, "name": s.name, "description": s.description, "category": s.category,
            "price_paise": s.price_paise, "duration_minutes": s.duration_minutes, "active": s.active}


def booking_view(b: Booking, *, admin: bool = False) -> dict:
    view = {"id": b.id, "service_id": b.service_id, "service_name": b.service_name, "status": b.status,
            "price_paise": b.price_paise, "scheduled_for": b.scheduled_for.isoformat() + "Z", "location_text": b.location_text,
            "notes": b.notes, "contact_name": b.contact_name, "created_at": b.created_at.isoformat() + "Z",
            "admin_note": b.admin_note}
    if admin:
        view.update(user_uid=b.user_uid, contact_phone=b.contact_phone, assigned_uid=b.assigned_uid, payment_id=b.payment_id)
    return view


async def list_services(db: AsyncSession, include_inactive: bool = False) -> list[dict]:
    query = select(ServiceItem).order_by(ServiceItem.category, ServiceItem.price_paise)
    if not include_inactive:
        query = query.where(ServiceItem.active.is_(True))
    return [service_view(s) for s in (await db.execute(query)).scalars().all()]


async def upsert_service(db: AsyncSession, data: dict) -> ServiceItem:
    item = await db.get(ServiceItem, data["id"])
    if item is None:
        item = ServiceItem(id=data["id"])
        db.add(item)
    for field in ("name", "description", "category", "price_paise", "duration_minutes", "active"):
        setattr(item, field, data[field])
    await db.flush()
    return item


async def create_booking(db: AsyncSession, user: AuthUser, data: dict, now: datetime | None = None) -> tuple[Booking, dict]:
    now = now or utcnow()
    acct = await accounts.ensure_account(db, user)
    if acct.is_blocked:
        raise ServiceError("Your account has been suspended. Contact support.", status=403, code="blocked")
    service = await db.get(ServiceItem, data["service_id"])
    if service is None or not service.active:
        raise ServiceError("That service is not available.", status=404, code="not_found")
    when = data["scheduled_for"]
    if when.tzinfo is None:                                           # a time without a zone is India time
        when = when.replace(tzinfo=IST)
    when = when.astimezone(timezone.utc).replace(tzinfo=None)         # stored as naive UTC like every other timestamp
    if when < now + timedelta(hours=MIN_LEAD_HOURS):
        raise ServiceError(f"Please book at least {MIN_LEAD_HOURS} hours ahead.", code="too_soon")
    if when > now + timedelta(days=MAX_ADVANCE_DAYS):
        raise ServiceError(f"Bookings open up to {MAX_ADVANCE_DAYS} days ahead.", code="too_far")
    phone = data["contact_phone"].strip()
    if not _PHONE.match(phone):
        raise ServiceError("Please enter a valid phone number so the pandit can reach you.", code="bad_phone")

    booking = Booking(user_uid=user.uid, service_id=service.id, service_name=service.name, status="pending_payment",
                      price_paise=service.price_paise, scheduled_for=when,
                      location_text=(data.get("location_text") or "").strip()[:300] or None,
                      notes=(data.get("notes") or "").strip()[:500] or None,
                      contact_name=data["contact_name"].strip(), contact_phone=phone, created_at=now, updated_at=now)
    db.add(booking)
    await db.flush()
    try:
        order = await billing.create_order(db, user, "booking", ref=booking.id, amount_paise=service.price_paise)
    except billing.BillingError as exc:
        raise ServiceError(exc.message, status=exc.status) from None
    booking.payment_id = order["payment_id"]
    return booking, order


async def on_paid(db: AsyncSession, payment: Payment) -> None:
    """Called by billing when a booking's payment is verified."""
    booking = await db.get(Booking, payment.ref, with_for_update=True)
    if booking is not None and booking.status == "pending_payment":
        booking.status, booking.updated_at = "paid", utcnow()


billing.register_paid_hook("booking", on_paid)


async def my_bookings(db: AsyncSession, uid: str, limit: int = 30) -> list[dict]:
    rows = (await db.execute(select(Booking).where(Booking.user_uid == uid)
                             .order_by(Booking.created_at.desc()).limit(limit))).scalars().all()
    return [booking_view(b) for b in rows]


async def _refund(db: AsyncSession, b: Booking, note: str) -> None:
    await wallet.credit(db, b.user_uid, b.price_paise, "refund", "booking", b.id, note=note)


async def cancel_booking(db: AsyncSession, uid: str, booking_id: str, now: datetime | None = None) -> Booking:
    now = now or utcnow()
    b = await db.get(Booking, booking_id, with_for_update=True)
    if b is None or b.user_uid != uid:
        raise ServiceError("Booking not found.", status=404, code="not_found")
    if b.status == "pending_payment":
        b.status = "cancelled"
    elif b.status == "paid":
        b.status = "refunded"
        await _refund(db, b, "Booking cancelled: refunded to your wallet")
    else:
        raise ServiceError("This booking can no longer be cancelled here. Please contact support.", status=409,
                           code="cannot_cancel")
    b.updated_at = now
    return b


async def admin_list(db: AsyncSession, status: str | None = None, limit: int = 100) -> list[dict]:
    query = select(Booking).order_by(Booking.scheduled_for).limit(limit)
    if status:
        query = query.where(Booking.status == status)
    return [booking_view(b, admin=True) for b in (await db.execute(query)).scalars().all()]


async def admin_set_status(db: AsyncSession, booking_id: str, status: str, assigned_uid: str | None = None,
                           note: str | None = None, now: datetime | None = None) -> Booking:
    b = await db.get(Booking, booking_id, with_for_update=True)
    if b is None:
        raise ServiceError("Booking not found.", status=404, code="not_found")
    if b.status not in _ADMIN_MOVES.get(status, set()):
        raise ServiceError(f"A booking that is {b.status} cannot become {status}.", status=409, code="bad_transition")
    if status == "refunded":
        await _refund(db, b, note or "Booking refunded to your wallet")
    if assigned_uid:
        b.assigned_uid = assigned_uid
    if note:
        b.admin_note = note
    b.status, b.updated_at = status, now or utcnow()
    return b
