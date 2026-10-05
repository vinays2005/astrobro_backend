"""
SQLAlchemy ORM models for AstroBro.

Tables:
  users    — registered users (original, unused by the routes)
  kundlis  — saved birth charts (one user can have many)
  chats    — conversation history per kundli
  accounts, entitlements, usage_daily, payments — who is calling, what they have paid for and used
  wallets, wallet_entries — prepaid balance for consultations (every change has a ledger row)
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
