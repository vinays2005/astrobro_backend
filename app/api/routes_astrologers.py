"""Astrologers: the public directory, and what an astrologer does for themselves (apply, go online, see requests)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db, session_scope
from app.database.models import EarningsEntry
from app.models.market import ApplyRequest, PresenceRequest, ProfileUpdate
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.services import accounts, astrologers, consult
from app.services.errors import ServiceError
from app.services.waiters import waiters

router = APIRouter(prefix="/api", tags=["astrologers"], dependencies=[Depends(require_api_key)])


@router.get("/astrologers")
async def list_astrologers(language: str | None = None, specialty: str | None = None,
                           mode: Literal["chat", "call", "video"] | None = None, online: bool = False,
                           sort: str = "online", limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                           db: AsyncSession = Depends(get_db)) -> dict:
    """Approved astrologers. Online ones come first unless another sort is asked for."""
    return await astrologers.directory(db, language=language, specialty=specialty, mode=mode, online_only=online,
                                       sort=sort, limit=limit, offset=offset)


@router.get("/astrologers/{uid}")
async def astrologer_profile(uid: str, db: AsyncSession = Depends(get_db)) -> dict:
    a = await astrologers.get(db, uid)
    if a is None or a.status != "approved":
        raise ServiceError("Astrologer not found.", status=404, code="not_found")
    return {**astrologers.public_profile(a), "reviews": await astrologers.reviews_for(db, uid)}


@router.post("/astrologer/apply")
async def apply(body: ApplyRequest, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    acct = await accounts.ensure_account(db, user)
    if acct.is_blocked:
        raise ServiceError("Your account has been suspended. Contact support.", status=403, code="blocked")
    a = await astrologers.apply(db, user, body.model_dump())
    return astrologers.own_profile(a)


@router.get("/astrologer/me")
async def my_profile(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    a = await astrologers.get(db, user.uid)
    if a is None:
        raise ServiceError("You have not applied to be an astrologer.", status=404, code="not_an_astrologer")
    return astrologers.own_profile(a)


@router.put("/astrologer/me")
async def update_profile(body: ProfileUpdate, user: AuthUser = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> dict:
    return astrologers.own_profile(await astrologers.update_profile(db, user.uid, body.model_dump(exclude_unset=True)))


@router.post("/astrologer/presence")
async def presence(body: PresenceRequest, user: AuthUser = Depends(current_user),
                   db: AsyncSession = Depends(get_db)) -> dict:
    """Go online or offline. The dashboard repeats this every ~25 seconds while it is open as a heartbeat."""
    return astrologers.own_profile(await astrologers.set_presence(db, user.uid, body.online))


@router.get("/astrologer/requests")
async def requests(wait: float = Query(0, ge=0, le=25), user: AuthUser = Depends(current_user)) -> dict:
    """Waiting requests and the consultation in progress. With `wait` it holds the call open until something arrives."""
    async with waiters.subscribe(consult.inbox_key(user.uid)) as event:
        async with session_scope() as db:
            a = await astrologers.get(db, user.uid)
            if a is None or a.status != "approved":
                raise ServiceError("Only approved astrologers have requests.", status=403, code="not_approved")
            await astrologers.touch(db, user.uid)
            inbox = await consult.astrologer_inbox(db, user.uid)
        if inbox["requests"] or inbox["active"] or wait <= 0:
            return inbox
        await waiters.wait(event, wait)
        async with session_scope() as db:
            await astrologers.touch(db, user.uid)
            return await consult.astrologer_inbox(db, user.uid)


@router.get("/astrologer/earnings")
async def earnings(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    a = await astrologers.get(db, user.uid)
    if a is None:
        raise ServiceError("You have not applied to be an astrologer.", status=404, code="not_an_astrologer")
    rows = (await db.execute(select(EarningsEntry).where(EarningsEntry.astrologer_uid == user.uid)
                             .order_by(EarningsEntry.id.desc()).limit(50))).scalars().all()
    return {"owed_paise": a.earnings_paise, "payout_upi": a.payout_upi,
            "entries": [{"id": e.id, "kind": e.kind, "amount_paise": e.amount_paise, "balance_after_paise": e.balance_after_paise,
                         "note": e.note, "created_at": e.created_at.isoformat() + "Z"} for e in rows]}
