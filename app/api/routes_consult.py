"""Consultations with human astrologers: request, accept, chat (long-polling), end, review.

Chat uses long-polling instead of WebSockets: GET .../messages?after=<last id>&wait=20 returns the moment a new
message or a state change arrives (or after `wait` seconds), so messages show up in well under a second, it works
through any proxy, and a dropped connection simply retries."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db, session_scope
from app.models.market import MessageRequest, ReportRequest, ReviewRequest, StartSessionRequest
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.security.ratelimit import limiter
from app.services import consult, wallet
from app.services.waiters import waiters

router = APIRouter(prefix="/api/consult", tags=["consult"], dependencies=[Depends(require_api_key)])
OVER = ("ended", "declined", "expired", "cancelled")
MESSAGES_PER_MINUTE = 40


async def _view(db: AsyncSession, uid: str, session_id: str) -> dict:
    s, role = await consult._participant_session(db, uid, session_id)
    return consult.session_view(s, role, consult.utcnow())


@router.post("/sessions")
async def start(body: StartSessionRequest, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    s = await consult.start_session(db, user, body.astrologer_uid, body.mode, body.topic,
                                    body.birth_data.model_dump() if body.birth_data else None)
    return {"session": consult.session_view(s, "user", consult.utcnow()), "wallet_balance_paise": await wallet.balance(db, user.uid)}


@router.get("/sessions")
async def my_sessions(role: Literal["user", "astrologer"] = "user", user: AuthUser = Depends(current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    return {"sessions": await consult.my_sessions(db, user.uid, role)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await _view(db, user.uid, session_id)


@router.post("/sessions/{session_id}/accept")
async def accept(session_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    s = await consult.accept_session(db, user.uid, session_id)
    return consult.session_view(s, "astrologer", consult.utcnow())


@router.post("/sessions/{session_id}/decline")
async def decline(session_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return consult.session_view(await consult.decline_session(db, user.uid, session_id), "astrologer", consult.utcnow())


@router.post("/sessions/{session_id}/cancel")
async def cancel(session_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return consult.session_view(await consult.cancel_request(db, user.uid, session_id), "user", consult.utcnow())


@router.post("/sessions/{session_id}/end")
async def end(session_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    s = await consult.end_session(db, user.uid, session_id)
    return {"session": consult.session_view(s, consult.role_in(s, user.uid), consult.utcnow()),
            "wallet_balance_paise": await wallet.balance(db, user.uid)}


@router.post("/sessions/{session_id}/messages")
async def send(session_id: str, body: MessageRequest, user: AuthUser = Depends(current_user),
               db: AsyncSession = Depends(get_db)) -> dict:
    if not limiter.allow(f"msg:{user.uid}", MESSAGES_PER_MINUTE, 60):
        raise HTTPException(status_code=429, detail={"error": "slow_down", "message": "You are sending messages too fast."})
    return consult.message_view(await consult.send_message(db, user.uid, session_id, body.body))


@router.get("/sessions/{session_id}/messages")
async def messages(session_id: str, after: int = Query(0, ge=0), wait: float = Query(0, ge=0, le=25),
                   user: AuthUser = Depends(current_user)) -> dict:
    """New messages after id `after`, plus the session state. With `wait`, holds the call open until news arrives."""
    async with waiters.subscribe(consult.session_key(session_id)) as event:      # subscribe first: nothing is missed
        async with session_scope() as db:
            new, view = await consult.messages_after(db, user.uid, session_id, after)
        if new or wait <= 0 or view["status"] in OVER:
            return {"messages": new, "session": view}
        await waiters.wait(event, wait)
        async with session_scope() as db:
            new, view = await consult.messages_after(db, user.uid, session_id, after)
        return {"messages": new, "session": view}


@router.post("/sessions/{session_id}/review")
async def review(session_id: str, body: ReviewRequest, user: AuthUser = Depends(current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    r = await consult.add_review(db, user.uid, session_id, body.rating, body.comment)
    return {"rating": r.rating, "comment": r.comment}


@router.post("/sessions/{session_id}/report")
async def report(session_id: str, body: ReportRequest, user: AuthUser = Depends(current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    r = await consult.report_abuse(db, user.uid, session_id, body.reason, body.details)
    return {"id": r.id, "status": r.status}
