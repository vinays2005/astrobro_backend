"""Charge AI calls against a user's daily allowance (or, for callers with no signed-in user, a per-address limit)."""
from __future__ import annotations

from dataclasses import dataclass

import structlog
from fastapi import HTTPException, Request

from app.config import get_settings
from app.database.connection import session_scope
from app.security.identity import AuthUser
from app.security.ratelimit import client_ip, limiter
from app.services import accounts

logger = structlog.get_logger()

ANON_CHATS_PER_HOUR = 40


@dataclass
class Meter:
    """What was charged for one AI call, so a failed call can be given back."""
    uid: str | None = None
    counted: bool = False


async def charge_ai_call(user: AuthUser | None, request: Request) -> Meter:
    """Count one AI chat. Raises 429 (limit_reached / slow_down) or 403 (suspended account)."""
    if user is None:
        if not limiter.allow(f"anon:{client_ip(request)}", ANON_CHATS_PER_HOUR, 3600):
            raise HTTPException(status_code=429, detail={
                "error": "slow_down", "message": "Too many requests from this device. Please try again later."})
        return Meter()

    async with session_scope() as db:
        acct = await accounts.ensure_account(db, user)
        if acct.is_blocked:
            raise HTTPException(status_code=403, detail="Your account has been suspended. Contact support.")
        allowed, used, limit = await accounts.consume_chat(db, user.uid)
    if not allowed:
        premium = get_settings().free_chats_per_day < limit
        raise HTTPException(status_code=429, detail={
            "error": "limit_reached", "used": used, "limit": limit, "premium": premium,
            "message": "You have used all of today's chats." if premium
            else "You have used your free chats for today. Upgrade for more."})
    return Meter(uid=user.uid, counted=True)


async def refund_ai_call(meter: Meter) -> None:
    """The AI failed: give the chat back."""
    if meter.counted and meter.uid:
        try:
            async with session_scope() as db:
                await accounts.release_chat(db, meter.uid)
        except Exception as exc:
            logger.warning("chat_refund_failed", error=str(exc))
