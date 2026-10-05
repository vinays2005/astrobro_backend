"""Prepaid wallet. Every change is one ledger row, a balance can never go below zero, and replaying the same
payment or the same billed minute changes nothing (the ledger row for a reference exists at most once)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Wallet, WalletEntry, utcnow

APPLIED, DUPLICATE, INSUFFICIENT = "applied", "duplicate", "insufficient"


async def _locked_wallet(db: AsyncSession, uid: str) -> Wallet:
    wallet = await db.get(Wallet, uid, with_for_update=True)
    if wallet is None:
        wallet = Wallet(uid=uid, balance_paise=0)
        db.add(wallet)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            wallet = await db.get(Wallet, uid, with_for_update=True)
    return wallet


async def balance(db: AsyncSession, uid: str) -> int:
    wallet = await db.get(Wallet, uid)
    return wallet.balance_paise if wallet else 0


async def _already_applied(db: AsyncSession, kind: str, ref_type: str | None, ref_id: str | None) -> bool:
    if ref_id is None:
        return False
    result = await db.execute(
        select(WalletEntry.id).where(WalletEntry.kind == kind, WalletEntry.ref_type == ref_type, WalletEntry.ref_id == ref_id)
    )
    return result.first() is not None


async def credit(db: AsyncSession, uid: str, amount_paise: int, kind: str, ref_type: str | None = None,
                 ref_id: str | None = None, note: str | None = None) -> str:
    if amount_paise <= 0:
        raise ValueError("A credit must be positive")
    wallet = await _locked_wallet(db, uid)
    if await _already_applied(db, kind, ref_type, ref_id):
        return DUPLICATE
    wallet.balance_paise += amount_paise
    wallet.updated_at = utcnow()
    db.add(WalletEntry(uid=uid, kind=kind, amount_paise=amount_paise, balance_after_paise=wallet.balance_paise,
                       ref_type=ref_type, ref_id=ref_id, note=note))
    await db.flush()
    return APPLIED


async def debit(db: AsyncSession, uid: str, amount_paise: int, kind: str, ref_type: str | None = None,
                ref_id: str | None = None, note: str | None = None) -> str:
    if amount_paise <= 0:
        raise ValueError("A debit must be positive")
    wallet = await _locked_wallet(db, uid)
    if await _already_applied(db, kind, ref_type, ref_id):
        return DUPLICATE
    if wallet.balance_paise < amount_paise:
        return INSUFFICIENT
    wallet.balance_paise -= amount_paise
    wallet.updated_at = utcnow()
    db.add(WalletEntry(uid=uid, kind=kind, amount_paise=-amount_paise, balance_after_paise=wallet.balance_paise,
                       ref_type=ref_type, ref_id=ref_id, note=note))
    await db.flush()
    return APPLIED


async def history(db: AsyncSession, uid: str, limit: int = 30) -> list[WalletEntry]:
    result = await db.execute(
        select(WalletEntry).where(WalletEntry.uid == uid).order_by(WalletEntry.id.desc()).limit(limit)
    )
    return list(result.scalars().all())
