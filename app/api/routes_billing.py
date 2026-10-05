"""Billing API: plans, Razorpay orders, payment verification and Razorpay's webhook.

The signed-in user (Firebase ID token) owns every order, and premium time, wallet money and report purchases are
granted here on the server after the payment is verified. The app never writes them itself."""
from __future__ import annotations

import json
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.connection import get_db, session_scope
from app.security.auth import require_api_key
from app.security.identity import AuthUser, current_user
from app.services import accounts, billing, wallet

logger = structlog.get_logger()
router = APIRouter(prefix="/api/billing", tags=["billing"], dependencies=[Depends(require_api_key)])
webhook_router = APIRouter(prefix="/api/billing", tags=["billing"])   # Razorpay cannot send our API key


class OrderRequest(BaseModel):
    purpose: Literal["plan", "report", "wallet"]
    plan_id: str | None = Field(default=None, max_length=20)
    amount_paise: int | None = Field(default=None, ge=1, le=10_000_000)


class VerifyRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=200)


def _http(exc: billing.BillingError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/plans")
async def plans() -> dict:
    """Prices and lengths of every plan, so the app never has to hard-code them."""
    s = get_settings()
    return {
        "plans": [{"id": pid, "price_paise": price, "days": days} for pid, (price, days) in accounts.PLANS.items()],
        "report_price_paise": s.paid_report_price,
        "report_free_for_premium": s.report_free_for_premium,
        "wallet": {"min_topup_paise": s.wallet_min_topup_paise, "max_topup_paise": s.wallet_max_topup_paise},
    }


@router.post("/orders")
async def create_order(body: OrderRequest, user: AuthUser = Depends(current_user),
                       db: AsyncSession = Depends(get_db)) -> dict:
    acct = await accounts.ensure_account(db, user)
    if acct.is_blocked:
        raise HTTPException(status_code=403, detail="Your account has been suspended. Contact support.")
    try:
        return await billing.create_order(db, user, body.purpose, ref=body.plan_id, amount_paise=body.amount_paise)
    except billing.BillingError as exc:
        raise _http(exc) from None


@router.post("/verify")
async def verify(body: VerifyRequest, user: AuthUser = Depends(current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    if not billing.signature_valid(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment verification failed")
    try:
        pay = await billing.settle(db, body.razorpay_order_id, body.razorpay_payment_id, uid=user.uid)
    except billing.BillingError as exc:
        raise _http(exc) from None
    until = await accounts.premium_until(db, user.uid)
    return {
        "success": True,
        "purpose": pay.purpose,
        "order_id": pay.razorpay_order_id,
        "premium_until": until.isoformat() + "Z" if until else None,
        "wallet_balance_paise": await wallet.balance(db, user.uid),
    }


@webhook_router.post("/webhook")
async def razorpay_webhook(request: Request) -> dict:
    """Settles payments even when the app was closed before it could call /verify.

    Set the same secret in Razorpay (Settings > Webhooks) and in RAZORPAY_WEBHOOK_SECRET, and subscribe to
    `payment.captured`. Without a secret this endpoint is off."""
    if not get_settings().razorpay_webhook_secret:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.body()
    if not billing.webhook_signature_valid(body, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(status_code=400, detail="Bad signature")
    try:
        event = json.loads(body)
        name = event.get("event")
        entity = event["payload"]["payment"]["entity"]
    except (ValueError, KeyError, TypeError):
        return {"ok": True, "ignored": True}
    if name in ("payment.captured", "order.paid") and entity.get("order_id") and entity.get("id"):
        try:
            async with session_scope() as db:
                await billing.settle(db, entity["order_id"], entity["id"], expected_amount=entity.get("amount"))
        except billing.BillingError as exc:       # unknown orders and replays are not errors for Razorpay
            logger.warning("webhook_not_settled", reason=exc.message, order_id=entity.get("order_id"))
    return {"ok": True}
