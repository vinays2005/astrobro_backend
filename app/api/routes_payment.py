"""Razorpay payment routes — create order & verify signature."""
from __future__ import annotations

import hashlib
import hmac

try:
    import razorpay
except ImportError:  # pkg_resources missing in some envs — mock for tests
    razorpay = None  # type: ignore[assignment]
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/payment", tags=["payment"])

PLAN_PRICES: dict[str, int] = {
    "monthly": 19900,   # ₹199 in paise
    "yearly":  99900,   # ₹999 in paise
}


def _razorpay_client():
    s = get_settings()
    if not s.razorpay_key_id or not s.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Payment service not configured")
    if razorpay is None:
        raise HTTPException(status_code=503, detail="razorpay package not available")
    return razorpay.Client(auth=(s.razorpay_key_id, s.razorpay_key_secret))


# ── Request/response models ───────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    plan_id: str   # "monthly" | "yearly"
    user_id: str


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str


class VerifyRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str
    user_id: str
    plan_id: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    dependencies=[Depends(require_api_key)],
)
async def create_order(body: CreateOrderRequest) -> dict:
    """Create a Razorpay order and return it to the Flutter app."""
    if body.plan_id not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan_id}")

    client = _razorpay_client()
    order = client.order.create({
        "amount":   PLAN_PRICES[body.plan_id],
        "currency": "INR",
        "receipt":  f"{body.user_id[:20]}_{body.plan_id}",
    })

    return {
        "order_id": order["id"],
        "amount":   order["amount"],
        "currency": "INR",
        "key_id":   get_settings().razorpay_key_id,
    }


@router.post(
    "/verify",
    dependencies=[Depends(require_api_key)],
)
async def verify_payment(body: VerifyRequest) -> dict:
    """Verify Razorpay HMAC signature — called after successful checkout."""
    secret = get_settings().razorpay_key_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Payment service not configured")

    payload = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    return {"success": True}
