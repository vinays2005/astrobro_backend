"""
Repository pattern — all DB access goes through these functions.
No raw SQL in routes. Errors fail loud.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Chat, Kundli, User


# ── User ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(
    db: AsyncSession, firebase_uid: str, email: str, display_name: str | None = None
) -> User:
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(firebase_uid=firebase_uid, email=email, display_name=display_name)
        db.add(user)
        await db.flush()
    return user


async def get_user_by_firebase_uid(db: AsyncSession, firebase_uid: str) -> User | None:
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    return result.scalar_one_or_none()


# ── Kundli ────────────────────────────────────────────────────────────────────

async def create_kundli(
    db: AsyncSession,
    user_id: str,
    name: str,
    date_of_birth: str,
    time_of_birth: str,
    timezone: str,
    latitude: float,
    longitude: float,
    chart_data: dict[str, Any],
    ayanamsa: str = "LAHIRI",
) -> Kundli:
    kundli = Kundli(
        user_id=user_id,
        name=name,
        date_of_birth=date_of_birth,
        time_of_birth=time_of_birth,
        timezone=timezone,
        latitude=latitude,
        longitude=longitude,
        ayanamsa=ayanamsa,
        chart_data=chart_data,
    )
    db.add(kundli)
    await db.flush()
    return kundli


async def get_kundlis_for_user(db: AsyncSession, user_id: str) -> list[Kundli]:
    result = await db.execute(
        select(Kundli).where(Kundli.user_id == user_id).order_by(Kundli.created_at.desc())
    )
    return list(result.scalars().all())


async def get_kundli_by_id(db: AsyncSession, kundli_id: str) -> Kundli | None:
    result = await db.execute(select(Kundli).where(Kundli.id == kundli_id))
    return result.scalar_one_or_none()


async def delete_kundli(db: AsyncSession, kundli_id: str, user_id: str) -> bool:
    """Delete kundli — only if it belongs to the user (ownership check)."""
    kundli = await get_kundli_by_id(db, kundli_id)
    if kundli is None or kundli.user_id != user_id:
        return False
    await db.delete(kundli)
    return True


# ── Chat history ──────────────────────────────────────────────────────────────

async def save_chat_message(
    db: AsyncSession,
    kundli_id: str,
    role: str,
    content: str,
    topic: str | None = None,
) -> Chat:
    if role not in ("user", "assistant"):
        raise ValueError(f"Invalid role: {role!r}. Must be 'user' or 'assistant'")
    msg = Chat(kundli_id=kundli_id, role=role, content=content, topic=topic)
    db.add(msg)
    await db.flush()
    return msg


async def get_chat_history(
    db: AsyncSession, kundli_id: str, limit: int = 20
) -> list[Chat]:
    result = await db.execute(
        select(Chat)
        .where(Chat.kundli_id == kundli_id)
        .order_by(Chat.created_at.desc())
        .limit(limit)
    )
    # Return oldest-first for context window ordering
    return list(reversed(result.scalars().all()))
