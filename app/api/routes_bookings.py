"""Pandit and puja bookings (user side). The admin side lives in routes_admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.models.market import BookingRequest
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.services import bookings

router = APIRouter(prefix="/api", tags=["bookings"], dependencies=[Depends(require_api_key)])


@router.get("/services")
async def services(db: AsyncSession = Depends(get_db)) -> dict:
    """What can be booked (pujas, homas, pandit visits)."""
    return {"services": await bookings.list_services(db)}


@router.post("/bookings")
async def create_booking(body: BookingRequest, user: AuthUser = Depends(current_user),
                         db: AsyncSession = Depends(get_db)) -> dict:
    """Creates the booking and a Razorpay order for it. Pay with the checkout, then call /api/billing/verify."""
    booking, order = await bookings.create_booking(db, user, body.model_dump())
    return {"booking": bookings.booking_view(booking), "order": order}


@router.get("/bookings")
async def my_bookings(user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {"bookings": await bookings.my_bookings(db, user.uid)}


@router.post("/bookings/{booking_id}/cancel")
async def cancel(booking_id: str, user: AuthUser = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return bookings.booking_view(await bookings.cancel_booking(db, user.uid, booking_id))
