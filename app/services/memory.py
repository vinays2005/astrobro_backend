"""Episodic memory: the AI remembers what a signed-in user asked in earlier chats.

Kept deliberately small and private:
  * only the user's own question and the first sentence of the reply are stored (no LLM call, no extra cost);
  * nothing is stored when the text holds contact details or crisis language;
  * at most MAX_PER_USER notes per person; the oldest are dropped;
  * only notes from earlier sessions are recalled (the live chat already carries the recent turns), at most
    MAX_RECALL of them, so a recall costs about 100-150 prompt tokens;
  * the user can list and delete their notes at any time (routes_me).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.astrology.intent import _CRISIS
from app.database.models import ChatMemory, utcnow
from app.services.moderation import contact_info_reason

MAX_PER_USER = 30
MAX_RECALL = 2
MIN_QUESTION_CHARS = 12
SAME_SESSION = timedelta(hours=2)        # newer notes are still in the live conversation history
_QUESTION_CHARS = 160
_GIST_CHARS = 140

_STOP = frozenset("""about above after again also because been before being between both could does doing from have having
here into just more most much must only other should some such than that their them then there these they this those
through very want what when where which while will with would your you are the and for not but can how why who""".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return _clip(m.group(1) if m else text, _GIST_CHARS)


def worth_keeping(question: str) -> bool:
    q = question.strip()
    return len(q) >= MIN_QUESTION_CHARS and contact_info_reason(q) is None and not _CRISIS.search(q)


async def remember(db: AsyncSession, uid: str, question: str, answer: str, now: datetime | None = None) -> bool:
    """Store one note. Returns False when the exchange is not worth keeping or is too sensitive to keep."""
    if not worth_keeping(question) or _CRISIS.search(answer or ""):
        return False
    now = now or utcnow()
    q = _clip(question, _QUESTION_CHARS)
    same = (await db.execute(select(ChatMemory).where(ChatMemory.uid == uid, ChatMemory.question == q))).scalars().first()
    if same:                                     # asked again: refresh instead of piling up copies
        same.gist, same.created_at = _first_sentence(answer or ""), now
    else:
        db.add(ChatMemory(uid=uid, question=q, gist=_first_sentence(answer or ""), created_at=now))
        await db.flush()
        extra = (await db.execute(
            select(ChatMemory.id).where(ChatMemory.uid == uid).order_by(ChatMemory.created_at.desc()).offset(MAX_PER_USER)
        )).scalars().all()
        if extra:
            await db.execute(delete(ChatMemory).where(ChatMemory.id.in_(extra)))
    return True


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 86400:
        return f"{max(1, seconds // 3600)} hours ago"
    days = seconds // 86400
    return "yesterday" if days == 1 else f"{days} days ago"


async def recall(db: AsyncSession, uid: str, question: str, now: datetime | None = None) -> str:
    """The notes worth bringing into this chat, as prompt lines, or '' when there is nothing from earlier sessions."""
    now = now or utcnow()
    rows = (await db.execute(
        select(ChatMemory).where(ChatMemory.uid == uid, ChatMemory.created_at <= now - SAME_SESSION)
        .order_by(ChatMemory.created_at.desc()).limit(MAX_PER_USER)
    )).scalars().all()
    if not rows:
        return ""
    asked = _words(question)
    related = sorted((r for r in rows if asked & _words(r.question)),
                     key=lambda r: (-len(asked & _words(r.question)), -r.created_at.timestamp()))
    chosen = related[:1] + [r for r in rows if r not in related[:1]][: MAX_RECALL - len(related[:1])]
    lines = []
    for r in chosen[:MAX_RECALL]:
        told = f" (I told them: {r.gist})" if r.gist else ""
        lines.append(f'- {_ago(r.created_at, now)} they asked: "{r.question}"{told}')
    return "\n".join(lines)


async def list_memories(db: AsyncSession, uid: str) -> list[ChatMemory]:
    return list((await db.execute(
        select(ChatMemory).where(ChatMemory.uid == uid).order_by(ChatMemory.created_at.desc()))).scalars().all())


async def forget(db: AsyncSession, uid: str, memory_id: str | None = None) -> int:
    """Delete one note (by id) or all of the user's notes. Returns how many were removed."""
    cond = [ChatMemory.uid == uid] + ([ChatMemory.id == memory_id] if memory_id else [])
    count = (await db.execute(select(func.count()).select_from(ChatMemory).where(*cond))).scalar_one()
    await db.execute(delete(ChatMemory).where(*cond))
    return int(count)
