"""Astrologer profiles: applying, approval by the admin, online presence and the public directory."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Astrologer, Review, utcnow
from app.security.identity import AuthUser
from app.services.errors import ServiceError

MODES = ("chat", "call", "video")
RATE_MIN_PAISE, RATE_MAX_PAISE = 500, 50_000          # Rs 5 to Rs 500 a minute
PRESENCE_TTL_SECONDS = 90                              # an astrologer who has not checked in for this long is offline
_UPI = re.compile(r"^[\w.\-]{2,64}@[A-Za-z]{2,32}$")
_STATUS_CHANGES = {
    "approved": {"pending", "rejected", "suspended"},
    "rejected": {"pending"},
    "suspended": {"approved"},
}


def clean_list(values, limit: int = 12, max_len: int = 30) -> list[str]:
    seen: list[str] = []
    for v in values or []:
        if v is None:
            continue
        text = re.sub(r"\s+", " ", str(v)).strip()[:max_len]
        if text and text.lower() not in (s.lower() for s in seen):
            seen.append(text)
    return seen[:limit]


def _check_rates(chat, call, video) -> None:
    offered = [r for r in (chat, call, video) if r is not None]
    if not offered:
        raise ServiceError("Offer at least one of chat, call or video, with a price per minute.", code="no_rates")
    for r in offered:
        if not RATE_MIN_PAISE <= r <= RATE_MAX_PAISE:
            raise ServiceError(f"Prices are between Rs {RATE_MIN_PAISE // 100} and Rs {RATE_MAX_PAISE // 100} a minute.",
                               code="bad_rate")


def _check_upi(upi: str | None) -> str | None:
    if upi is None or upi.strip() == "":
        return None
    upi = upi.strip()
    if not _UPI.match(upi):
        raise ServiceError("That does not look like a UPI id (name@bank).", code="bad_upi")
    return upi


def _check_photo(url: str | None) -> str | None:
    if url is None or url.strip() == "":
        return None
    url = url.strip()
    if not url.startswith("https://") or len(url) > 500:
        raise ServiceError("The photo link must start with https://", code="bad_photo")
    return url


def rate_for(a: Astrologer, mode: str) -> int | None:
    return {"chat": a.chat_rate_paise, "call": a.call_rate_paise, "video": a.video_rate_paise}[mode]


def is_online(a: Astrologer, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return bool(a.status == "approved" and a.is_online and a.last_seen_at
                and now - a.last_seen_at <= timedelta(seconds=PRESENCE_TTL_SECONDS))


def public_profile(a: Astrologer, now: datetime | None = None) -> dict:
    """What users may see. Never the payout details, status notes or earnings."""
    return {
        "uid": a.uid, "name": a.name, "bio": a.bio, "photo_url": a.photo_url, "languages": a.languages or [],
        "specialties": a.specialties or [], "experience_years": a.experience_years,
        "rates_paise_per_min": {m: rate_for(a, m) for m in MODES if rate_for(a, m) is not None},
        "online": is_online(a, now), "rating": round(a.rating_avg, 1), "rating_count": a.rating_count,
        "sessions_count": a.sessions_count,
    }


def own_profile(a: Astrologer, now: datetime | None = None) -> dict:
    return {**public_profile(a, now), "status": a.status, "status_note": a.status_note, "payout_upi": a.payout_upi,
            "earnings_paise": a.earnings_paise, "minutes_total": a.minutes_total}


async def get(db: AsyncSession, uid: str, *, lock: bool = False) -> Astrologer | None:
    return await db.get(Astrologer, uid, with_for_update=lock)


async def apply(db: AsyncSession, user: AuthUser, data: dict) -> Astrologer:
    _check_rates(data.get("chat_rate_paise"), data.get("call_rate_paise"), data.get("video_rate_paise"))
    existing = await get(db, user.uid, lock=True)
    if existing is not None and existing.status != "rejected":
        raise ServiceError("You have already applied.", status=409, code="already_applied")
    a = existing or Astrologer(uid=user.uid, name="")
    a.name = data["name"].strip()
    a.bio = data.get("bio", "").strip()
    a.photo_url = _check_photo(data.get("photo_url"))
    a.languages = clean_list(data.get("languages"))
    a.specialties = clean_list(data.get("specialties"))
    a.experience_years = int(data.get("experience_years") or 0)
    a.chat_rate_paise = data.get("chat_rate_paise")
    a.call_rate_paise = data.get("call_rate_paise")
    a.video_rate_paise = data.get("video_rate_paise")
    a.payout_upi = _check_upi(data.get("payout_upi"))
    a.status, a.status_note, a.is_online = "pending", None, False
    if existing is None:
        db.add(a)
    await db.flush()
    return a


async def update_profile(db: AsyncSession, uid: str, data: dict) -> Astrologer:
    a = await get(db, uid, lock=True)
    if a is None:
        raise ServiceError("Apply to become an astrologer first.", status=404, code="not_an_astrologer")
    if "name" in data and data["name"]:
        a.name = data["name"].strip()
    if "bio" in data and data["bio"] is not None:
        a.bio = data["bio"].strip()
    if "photo_url" in data:
        a.photo_url = _check_photo(data["photo_url"])
    if "languages" in data and data["languages"] is not None:
        a.languages = clean_list(data["languages"])
    if "specialties" in data and data["specialties"] is not None:
        a.specialties = clean_list(data["specialties"])
    if data.get("experience_years") is not None:
        a.experience_years = int(data["experience_years"])
    if "payout_upi" in data:
        a.payout_upi = _check_upi(data["payout_upi"])
    rates = {k: data[k] if k in data else getattr(a, k) for k in ("chat_rate_paise", "call_rate_paise", "video_rate_paise")}
    _check_rates(**{k.replace("_rate_paise", ""): v for k, v in rates.items()})
    a.chat_rate_paise, a.call_rate_paise, a.video_rate_paise = rates["chat_rate_paise"], rates["call_rate_paise"], rates["video_rate_paise"]
    await db.flush()
    return a


async def set_presence(db: AsyncSession, uid: str, online: bool, now: datetime | None = None) -> Astrologer:
    a = await get(db, uid, lock=True)
    if a is None or a.status != "approved":
        raise ServiceError("Only approved astrologers can go online.", status=403, code="not_approved")
    a.is_online = online
    a.last_seen_at = now or utcnow()
    await db.flush()
    return a


async def touch(db: AsyncSession, uid: str, now: datetime | None = None, *, even_if_offline: bool = False) -> None:
    """An astrologer polling for requests is present: keep them online without a separate heartbeat call.

    `even_if_offline` is for an astrologer who switched themselves offline to stop new requests but is still
    talking to someone: their last-seen time is kept fresh so that consultation is not ended as abandoned, while
    they stay out of the online list."""
    a = await get(db, uid)
    if a is not None and a.status == "approved" and (a.is_online or even_if_offline):
        a.last_seen_at = now or utcnow()


async def directory(db: AsyncSession, *, now: datetime | None = None, language: str | None = None,
                    specialty: str | None = None, mode: str | None = None, online_only: bool = False,
                    sort: str = "online", limit: int = 20, offset: int = 0) -> dict:
    now = now or utcnow()
    rows = (await db.execute(select(Astrologer).where(Astrologer.status == "approved").limit(1000))).scalars().all()

    def has(values, wanted):
        return wanted.lower() in (v.lower() for v in values or [])

    items = [a for a in rows
             if (not language or has(a.languages, language)) and (not specialty or has(a.specialties, specialty))
             and (not mode or rate_for(a, mode) is not None) and (not online_only or is_online(a, now))]
    keys = {
        "rating": lambda a: (-a.rating_avg, -a.rating_count),
        "price_low": lambda a: min((r for r in (a.chat_rate_paise, a.call_rate_paise, a.video_rate_paise) if r), default=10**9),
        "price_high": lambda a: -max((r for r in (a.chat_rate_paise, a.call_rate_paise, a.video_rate_paise) if r), default=0),
        "experience": lambda a: -a.experience_years,
        "online": lambda a: (not is_online(a, now), -a.rating_avg, -a.rating_count),
    }
    if sort not in keys:
        raise ServiceError(f"sort must be one of: {', '.join(keys)}", code="bad_sort")
    items.sort(key=keys[sort])
    page = items[offset: offset + limit]
    return {"total": len(items), "items": [public_profile(a, now) for a in page]}


async def reviews_for(db: AsyncSession, uid: str, limit: int = 10) -> list[dict]:
    rows = (await db.execute(select(Review).where(Review.astrologer_uid == uid).order_by(Review.id.desc()).limit(limit))).scalars().all()
    return [{"rating": r.rating, "comment": r.comment, "created_at": r.created_at.isoformat() + "Z"} for r in rows]


async def set_status(db: AsyncSession, uid: str, status: str, note: str | None = None) -> Astrologer:
    a = await get(db, uid, lock=True)
    if a is None:
        raise ServiceError("No such astrologer.", status=404)
    if a.status not in _STATUS_CHANGES.get(status, set()):
        raise ServiceError(f"An astrologer who is {a.status} cannot become {status}.", status=409, code="bad_transition")
    a.status, a.status_note = status, (note or None)
    if status == "approved":
        a.approved_at = utcnow()
    else:
        a.is_online = False
    await db.flush()
    return a
