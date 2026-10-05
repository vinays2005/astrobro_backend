"""
SQLAlchemy ORM models for AstroBro.

Tables:
  users    — registered users (original, unused by the routes)
  kundlis  — saved birth charts (one user can have many)
  chats    — conversation history per kundli
  accounts, entitlements, usage_daily, payments — who is calling, what they have paid for and used
  wallets, wallet_entries — prepaid balance for consultations (every change has a ledger row)
  astrologers, consult_sessions, consult_messages, earnings_entries, reviews, abuse_reports — human consultations
  service_items, bookings — pandit and puja bookings
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC timestamp: every DateTime column in these tables holds UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)

    kundlis: Mapped[list["Kundli"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Kundli(Base):
    __tablename__ = "kundlis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[str] = mapped_column(String(10))     # YYYY-MM-DD
    time_of_birth: Mapped[str] = mapped_column(String(5))      # HH:MM
    timezone: Mapped[str] = mapped_column(String(50))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    ayanamsa: Mapped[str] = mapped_column(String(20), default="LAHIRI")
    chart_data: Mapped[dict] = mapped_column(JSON)             # full chart dict
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="kundlis")
    chats: Mapped[list["Chat"]] = relationship(back_populates="kundli", cascade="all, delete-orphan")


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    kundli_id: Mapped[str] = mapped_column(ForeignKey("kundlis.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))              # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    kundli: Mapped["Kundli"] = relationship(back_populates="chats")


# ── Accounts, plans, usage and payments (server-side source of truth) ─────────

class Account(Base):
    """One row per Firebase user, created the first time they use a signed-in feature."""
    __tablename__ = "accounts"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)   # 18+ and consultation terms


class Entitlement(Base):
    """Premium access. Written only by the server after a payment is verified."""
    __tablename__ = "entitlements"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan: Mapped[str] = mapped_column(String(20), default="premium")
    valid_until: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsageDaily(Base):
    """AI chats used per user per Indian calendar day (the free limit is enforced against this)."""
    __tablename__ = "usage_daily"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    chats: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    """A Razorpay order and what it buys. The audit trail for every rupee the app takes."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    uid: Mapped[str] = mapped_column(String(128), index=True)
    purpose: Mapped[str] = mapped_column(String(20))              # plan | report | wallet | booking
    ref: Mapped[str | None] = mapped_column(String(64))           # plan id, booking id, ...
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    razorpay_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="created")    # created | paid
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)       # one-time purchases (a report) are spent once


# ── Wallet ────────────────────────────────────────────────────────────────────

class Wallet(Base):
    """Prepaid balance. Only changed through app/services/wallet.py, which writes a ledger row each time."""
    __tablename__ = "wallets"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    balance_paise: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalletEntry(Base):
    """One credit or debit. (kind, ref_type, ref_id) is unique, so replaying a payment or a billed minute is harmless."""
    __tablename__ = "wallet_entries"
    __table_args__ = (UniqueConstraint("kind", "ref_type", "ref_id", name="uq_wallet_entry_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(20))                 # topup | consult_charge | refund | adjustment
    amount_paise: Mapped[int] = mapped_column(Integer)            # signed: credits positive, debits negative
    balance_after_paise: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str | None] = mapped_column(String(20))      # payment | session | admin
    ref_id: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── Human astrologers: profiles, consultations, earnings ─────────────────────

class Astrologer(Base):
    """A person who consults with users. Listed only after an admin approves them."""
    __tablename__ = "astrologers"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    bio: Mapped[str] = mapped_column(Text, default="")
    photo_url: Mapped[str | None] = mapped_column(String(500))
    languages: Mapped[list] = mapped_column(JSON, default=list)
    specialties: Mapped[list] = mapped_column(JSON, default=list)
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    chat_rate_paise: Mapped[int | None] = mapped_column(Integer)      # per minute; None = not offered
    call_rate_paise: Mapped[int | None] = mapped_column(Integer)
    video_rate_paise: Mapped[int | None] = mapped_column(Integer)
    payout_upi: Mapped[str | None] = mapped_column(String(100))       # where the admin sends earnings; never shown to users
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)   # pending | approved | rejected | suspended
    status_note: Mapped[str | None] = mapped_column(String(300))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    rating_avg: Mapped[float] = mapped_column(Float, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    sessions_count: Mapped[int] = mapped_column(Integer, default=0)
    minutes_total: Mapped[int] = mapped_column(Integer, default=0)
    earnings_paise: Mapped[int] = mapped_column(Integer, default=0)   # earned and not yet paid out
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)


class ConsultSession(Base):
    """One consultation. Billed a minute at a time from the user's wallet (see app/services/consult.py)."""
    __tablename__ = "consult_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_uid: Mapped[str] = mapped_column(String(128), index=True)
    astrologer_uid: Mapped[str] = mapped_column(String(128), index=True)
    mode: Mapped[str] = mapped_column(String(8))                      # chat | call | video
    status: Mapped[str] = mapped_column(String(12), default="requested", index=True)
    # requested | active | ended | declined | expired | cancelled
    rate_paise_per_min: Mapped[int] = mapped_column(Integer)
    commission_percent: Mapped[int] = mapped_column(Integer)
    topic: Mapped[str | None] = mapped_column(String(200))
    birth_snapshot: Mapped[dict | None] = mapped_column(JSON)         # birth details the user chose to share
    room: Mapped[str | None] = mapped_column(String(80))              # video/voice room name
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_by: Mapped[str | None] = mapped_column(String(12))          # user | astrologer | system
    end_reason: Mapped[str | None] = mapped_column(String(40))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    billed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    charged_paise: Mapped[int] = mapped_column(Integer, default=0)
    astrologer_earned_paise: Mapped[int] = mapped_column(Integer, default=0)
    refunded_paise: Mapped[int] = mapped_column(Integer, default=0)


class ConsultMessage(Base):
    __tablename__ = "consult_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    sender_uid: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(8), default="text")      # text | system
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EarningsEntry(Base):
    """An astrologer's ledger: money earned per billed minute, and payouts the admin has sent."""
    __tablename__ = "earnings_entries"
    __table_args__ = (UniqueConstraint("kind", "ref_type", "ref_id", name="uq_earnings_entry_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    astrologer_uid: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(12))                     # consult | payout | adjustment
    amount_paise: Mapped[int] = mapped_column(Integer)                # earned positive, paid out negative
    balance_after_paise: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), unique=True)
    user_uid: Mapped[str] = mapped_column(String(128))
    astrologer_uid: Mapped[str] = mapped_column(String(128), index=True)
    rating: Mapped[int] = mapped_column(Integer)                      # 1..5
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AbuseReport(Base):
    __tablename__ = "abuse_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_uid: Mapped[str] = mapped_column(String(128))
    target_uid: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(40))
    details: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="open")   # open | reviewed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ── Pandit and puja bookings ──────────────────────────────────────────────────

class ServiceItem(Base):
    """Something a user can book: a puja, a homa, a pandit visit. Managed by the admin."""
    __tablename__ = "service_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)     # slug
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="puja")
    price_paise: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_uid: Mapped[str] = mapped_column(String(128), index=True)
    service_id: Mapped[str] = mapped_column(String(40))
    service_name: Mapped[str] = mapped_column(String(120))            # copied, so later renames do not rewrite history
    status: Mapped[str] = mapped_column(String(16), default="pending_payment", index=True)
    # pending_payment | paid | confirmed | completed | cancelled | refunded
    price_paise: Mapped[int] = mapped_column(Integer)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime)
    location_text: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(String(500))
    contact_name: Mapped[str] = mapped_column(String(100))
    contact_phone: Mapped[str] = mapped_column(String(20))
    payment_id: Mapped[str | None] = mapped_column(String(36))        # payments.id
    assigned_uid: Mapped[str | None] = mapped_column(String(128))
    admin_note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
