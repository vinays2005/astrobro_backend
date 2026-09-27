"""
SQLAlchemy ORM models for AstroBro.

Tables:
  users    — registered users
  kundlis  — saved birth charts (one user can have many)
  chats    — conversation history per kundli
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _new_uuid() -> str:
    return str(uuid.uuid4())


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
