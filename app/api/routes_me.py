"""The signed-in user's own account: plan, today's AI allowance and wallet."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.connection import get_db
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.services import accounts, astrologers, erasure, wallet
from app.services import memory as chat_memory

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


@router.delete("/me")
async def delete_me(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Erase the caller's data before the app deletes their Firebase account. 409 (wallet_not_empty,
    consult_in_progress, booking_in_progress, earnings_unpaid) while money or a service is still in flight."""
    return await erasure.delete_account(db, user.uid, user.email)


@router.post("/me/accept-terms")
async def accept_terms(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The user confirms they are 18+ and accepts the consultation terms (needed before the first consultation)."""
    await accounts.accept_terms(db, user)
    return await account_summary(db, user)


@router.get("/me/memories")
async def my_memories(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Everything the AI remembers about this user's earlier chats."""
    items = await chat_memory.list_memories(db, user.uid)
    return {"memories": [{"id": m.id, "question": m.question, "gist": m.gist, "created_at": _iso(m.created_at)} for m in items]}


@router.delete("/me/memories")
async def forget_all_memories(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Forget everything."""
    return {"deleted": await chat_memory.forget(db, user.uid)}


@router.delete("/me/memories/{memory_id}")
async def forget_one_memory(memory_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    deleted = await chat_memory.forget(db, user.uid, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="That memory was not found.")
    return {"deleted": deleted}


@router.get("/wallet")
async def my_wallet(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await accounts.ensure_account(db, user)
    entries = await wallet.history(db, user.uid)
    return {
        "balance_paise": await wallet.balance(db, user.uid),
        "entries": [{"id": e.id, "kind": e.kind, "amount_paise": e.amount_paise, "balance_after_paise": e.balance_after_paise,
                     "note": e.note, "created_at": _iso(e.created_at)} for e in entries],
    }
