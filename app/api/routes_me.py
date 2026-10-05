"""The signed-in user's own account: plan, today's AI allowance and wallet."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.connection import get_db
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.services import accounts, astrologers, wallet

router = APIRouter(prefix="/api", tags=["me"], dependencies=[Depends(require_api_key)])


def _iso(dt) -> str | None:
    return dt.isoformat() + "Z" if dt else None


async def account_summary(db: AsyncSession, user: AuthUser) -> dict:
    """Everything the app needs to draw the plan, limit and wallet state. The server is the source of truth."""
    acct = await accounts.ensure_account(db, user)
    until = await accounts.premium_until(db, user.uid)
    astrologer = await astrologers.get(db, user.uid)
    s = get_settings()
    limit = s.premium_chats_per_day if until else s.free_chats_per_day
    used = await accounts.usage_today(db, user.uid)
    return {
        "uid": user.uid,
        "email": user.email,
        "plan": "premium" if until else "free",
        "premium_until": _iso(until),
        "chats_used_today": used,
        "chat_limit": limit,
        "chats_remaining": max(0, limit - used),
        "wallet_balance_paise": await wallet.balance(db, user.uid),
        "is_admin": user.is_admin,
        "terms_accepted": acct.terms_accepted_at is not None,
        "astrologer_status": astrologer.status if astrologer else None,
    }


@router.get("/me")
async def me(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await account_summary(db, user)


@router.post("/me/accept-terms")
async def accept_terms(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The user confirms they are 18+ and accepts the consultation terms (needed before the first consultation)."""
    await accounts.accept_terms(db, user)
    return await account_summary(db, user)


@router.get("/wallet")
async def my_wallet(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await accounts.ensure_account(db, user)
    entries = await wallet.history(db, user.uid)
    return {
        "balance_paise": await wallet.balance(db, user.uid),
        "entries": [{"id": e.id, "kind": e.kind, "amount_paise": e.amount_paise, "balance_after_paise": e.balance_after_paise,
                     "note": e.note, "created_at": _iso(e.created_at)} for e in entries],
    }
