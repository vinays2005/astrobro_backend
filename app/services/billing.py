"""Razorpay orders, and what a verified payment buys (premium time, wallet money, a one-time report)."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Awaitable, Callable

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import Payment, utcnow
from app.security.identity import AuthUser
from app.services import accounts, wallet

logger = structlog.get_logger()

PaidHook = Callable[[AsyncSession, Payment], Awaitable[None]]
_paid_hooks: dict[str, PaidHook] = {}


class BillingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def register_paid_hook(purpose: str, hook: PaidHook) -> None:
    """Let another module (bookings) react when a payment of its purpose is verified."""
    _paid_hooks[purpose] = hook


# ── Razorpay ──────────────────────────────────────────────────────────────────

RAZORPAY_API = "https://api.razorpay.com/v1"


async def create_razorpay_order(payload: dict, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Create an order through Razorpay's REST API. (The official Python SDK imports pkg_resources, which newer
    Python environments no longer ship, so the one call we need is made directly.)"""
    s = get_settings()
    if not s.razorpay_key_id or not s.razorpay_key_secret:
        raise BillingError("Payments are not set up yet.", 503)
    async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
        resp = await client.post(f"{RAZORPAY_API}/orders", json=payload, auth=(s.razorpay_key_id, s.razorpay_key_secret))
    if resp.status_code >= 400:
        logger.error("razorpay_order_rejected", status=resp.status_code, body=resp.text[:300])
        raise BillingError("Could not start the payment. Please try again.", 502)
    return resp.json()


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_valid(order_id: str, payment_id: str, signature: str) -> bool:
    secret = get_settings().razorpay_key_secret
    if not secret or not order_id or not payment_id:
        return False
    return hmac.compare_digest(_hmac_hex(secret, f"{order_id}|{payment_id}".encode()), signature or "")


def webhook_signature_valid(body: bytes, signature: str) -> bool:
    secret = get_settings().razorpay_webhook_secret
    return bool(secret) and hmac.compare_digest(_hmac_hex(secret, body), signature or "")


# ── Orders ────────────────────────────────────────────────────────────────────

def price_for(purpose: str, ref: str | None, amount_paise: int | None) -> int:
    s = get_settings()
    if purpose == "plan":
        if ref not in accounts.PLANS:
            raise BillingError("Unknown plan")
        return accounts.PLANS[ref][0]
    if purpose == "report":
        return s.paid_report_price
    if purpose == "wallet":
        low, high = s.wallet_min_topup_paise, s.wallet_max_topup_paise
        if amount_paise is None or not low <= amount_paise <= high:
            raise BillingError(f"Wallet top-ups are between Rs {low // 100} and Rs {high // 100}.")
        return amount_paise
    raise BillingError("Unsupported purchase")


async def create_order(db: AsyncSession, user: AuthUser, purpose: str, ref: str | None = None,
                       amount_paise: int | None = None) -> dict:
    amount = amount_paise if purpose == "booking" else price_for(purpose, ref, amount_paise)
    if not amount or amount <= 0:
        raise BillingError("Invalid amount")
    try:
        order = await create_razorpay_order({
            "amount": amount, "currency": "INR", "receipt": f"{purpose[:3]}-{uuid.uuid4().hex[:16]}",
            "notes": {"uid": user.uid, "purpose": purpose, "ref": ref or ""},
        })
    except BillingError:
        raise
    except Exception as exc:
        logger.error("razorpay_order_failed", error=str(exc))
        raise BillingError("Could not start the payment. Please try again.", 502) from None
    pay = Payment(uid=user.uid, purpose=purpose, ref=ref, amount_paise=amount, razorpay_order_id=order["id"])
    db.add(pay)
    await db.flush()
    return {"payment_id": pay.id, "order_id": order["id"], "amount": amount, "currency": "INR",
            "key_id": get_settings().razorpay_key_id, "purpose": purpose}


# ── Settling a payment ────────────────────────────────────────────────────────

async def settle(db: AsyncSession, order_id: str, payment_id: str, *, uid: str | None = None,
                 expected_amount: int | None = None) -> Payment:
    """Mark an order paid and apply what it buys. Safe to call any number of times for the same order."""
    result = await db.execute(select(Payment).where(Payment.razorpay_order_id == order_id).with_for_update())
    pay = result.scalar_one_or_none()
    if pay is None:
        raise BillingError("Unknown order", 404)
    if uid is not None and pay.uid != uid:
        raise BillingError("This payment belongs to another account", 403)
    if expected_amount is not None and expected_amount != pay.amount_paise:
        raise BillingError("Amount does not match the order", 409)
    if pay.status == "paid":
        return pay
    pay.status = "paid"
    pay.razorpay_payment_id = payment_id
    pay.paid_at = utcnow()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise BillingError("This payment id was already used", 409) from None
    await _apply(db, pay)
    return pay


async def _apply(db: AsyncSession, pay: Payment) -> None:
    if pay.purpose == "plan":
        await accounts.grant_premium(db, pay.uid, accounts.PLANS[pay.ref][1])
    elif pay.purpose == "wallet":
        await wallet.credit(db, pay.uid, pay.amount_paise, "topup", "payment", pay.id, note="Wallet top-up")
    hook = _paid_hooks.get(pay.purpose)
    if hook is not None:
        await hook(db, pay)


# ── One-time report purchases ─────────────────────────────────────────────────

async def consume_report_payment(db: AsyncSession, uid: str, order_id: str) -> bool:
    """Spend a paid report order. True only the first time, so one payment buys one report."""
    result = await db.execute(
        update(Payment)
        .where(Payment.razorpay_order_id == order_id, Payment.uid == uid, Payment.purpose == "report",
               Payment.status == "paid", Payment.consumed_at.is_(None))
        .values(consumed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def unconsume_report_payment(db: AsyncSession, uid: str, order_id: str) -> None:
    """Give the report back when generating it failed."""
    await db.execute(
        update(Payment).where(Payment.razorpay_order_id == order_id, Payment.uid == uid)
        .values(consumed_at=None).execution_options(synchronize_session=False)
    )
