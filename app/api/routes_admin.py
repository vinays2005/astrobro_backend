"""Owner tools. Every route needs the API key AND a signed-in user whose verified email (or uid) is in ADMIN_EMAILS /
ADMIN_UIDS, so the key inside the app alone gives no access."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.models.market import (AdminNote, BlockRequest, BookingStatusRequest, PayoutRequest, ServiceUpsert,
                               WalletAdjustRequest)
from app.security.auth import require_api_key
from app.security.identity import AuthUser, admin_user
from app.services import admin, astrologers, bookings

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_api_key), Depends(admin_user)])


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    return await admin.summary(db)


@router.get("/astrologers")
async def astrologer_applications(status: str = Query("pending", pattern="^(pending|approved|rejected|suspended)$"),
                                  db: AsyncSession = Depends(get_db)) -> dict:
    return {"astrologers": await admin.pending_astrologers(db, status)}


async def _change(db: AsyncSession, uid: str, status: str, note: str | None) -> dict:
    return astrologers.own_profile(await astrologers.set_status(db, uid, status, note))


@router.post("/astrologers/{uid}/approve")
async def approve(uid: str, body: AdminNote | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    return await _change(db, uid, "approved", body.note if body else None)


@router.post("/astrologers/{uid}/reject")
async def reject(uid: str, body: AdminNote, db: AsyncSession = Depends(get_db)) -> dict:
    return await _change(db, uid, "rejected", body.note)


@router.post("/astrologers/{uid}/suspend")
async def suspend(uid: str, body: AdminNote, db: AsyncSession = Depends(get_db)) -> dict:
    return await _change(db, uid, "suspended", body.note)


@router.post("/payouts")
async def payouts(body: PayoutRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Record a payout you have already sent to the astrologer (UPI/bank). It reduces what you owe them."""
    return await admin.payout(db, body.astrologer_uid, body.amount_paise, body.note)


@router.post("/wallet/adjust")
async def wallet_adjust(body: WalletAdjustRequest, db: AsyncSession = Depends(get_db)) -> dict:
    return await admin.adjust_wallet(db, body.uid, body.amount_paise, body.note)


@router.get("/wallet/{uid}")
async def wallet_statement(uid: str, db: AsyncSession = Depends(get_db)) -> dict:
    return await admin.wallet_statement(db, uid)


@router.post("/accounts/{uid}/block")
async def block(uid: str, body: BlockRequest, db: AsyncSession = Depends(get_db)) -> dict:
    return await admin.set_blocked(db, uid, body.blocked)


@router.get("/reports")
async def reports(status: str = Query("open", pattern="^(open|reviewed)$"), db: AsyncSession = Depends(get_db)) -> dict:
    return {"reports": await admin.open_reports(db, status)}


@router.post("/reports/{report_id}/resolve")
async def resolve(report_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    return await admin.resolve_report(db, report_id)


@router.get("/services")
async def all_services(db: AsyncSession = Depends(get_db)) -> dict:
    return {"services": await bookings.list_services(db, include_inactive=True)}


@router.put("/services")
async def upsert_service(body: ServiceUpsert, db: AsyncSession = Depends(get_db)) -> dict:
    return bookings.service_view(await bookings.upsert_service(db, body.model_dump()))


@router.get("/bookings")
async def all_bookings(status: str | None = Query(None, pattern="^(pending_payment|paid|confirmed|completed|refunded|cancelled)$"),
                       db: AsyncSession = Depends(get_db)) -> dict:
    return {"bookings": await bookings.admin_list(db, status)}


@router.post("/bookings/{booking_id}/status")
async def booking_status(booking_id: str, body: BookingStatusRequest, db: AsyncSession = Depends(get_db),
                         user: AuthUser = Depends(admin_user)) -> dict:
    b = await bookings.admin_set_status(db, booking_id, body.status, body.assigned_uid, body.note)
    return bookings.booking_view(b, admin=True)
