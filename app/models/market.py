"""Request bodies for the marketplace: astrologers, consultations, bookings and the admin."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.api import BirthData

Rate = Field(default=None, ge=1, le=1_000_000)


class ApplyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    bio: str = Field(default="", max_length=1000)
    photo_url: str | None = Field(default=None, max_length=500)
    languages: list[str] = Field(default_factory=list, max_length=20)
    specialties: list[str] = Field(default_factory=list, max_length=20)
    experience_years: int = Field(default=0, ge=0, le=70)
    chat_rate_paise: int | None = Rate
    call_rate_paise: int | None = Rate
    video_rate_paise: int | None = Rate
    payout_upi: str | None = Field(default=None, max_length=100)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    bio: str | None = Field(default=None, max_length=1000)
    photo_url: str | None = Field(default=None, max_length=500)
    languages: list[str] | None = Field(default=None, max_length=20)
    specialties: list[str] | None = Field(default=None, max_length=20)
    experience_years: int | None = Field(default=None, ge=0, le=70)
    chat_rate_paise: int | None = Rate
    call_rate_paise: int | None = Rate
    video_rate_paise: int | None = Rate
    payout_upi: str | None = Field(default=None, max_length=100)


class PresenceRequest(BaseModel):
    online: bool


class StartSessionRequest(BaseModel):
    astrologer_uid: str = Field(min_length=1, max_length=128)
    mode: Literal["chat", "call", "video"] = "chat"
    topic: str | None = Field(default=None, max_length=200)
    birth_data: BirthData | None = None


class MessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class ReportRequest(BaseModel):
    reason: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=500)


class AdminNote(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class PayoutRequest(BaseModel):
    astrologer_uid: str = Field(min_length=1, max_length=128)
    amount_paise: int = Field(ge=100, le=100_000_000)
    note: str | None = Field(default=None, max_length=200)


class WalletAdjustRequest(BaseModel):
    uid: str = Field(min_length=1, max_length=128)
    amount_paise: int = Field(ge=-10_000_000, le=10_000_000)
    note: str = Field(min_length=3, max_length=200)


class BlockRequest(BaseModel):
    blocked: bool


class ServiceUpsert(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,38}$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="puja", max_length=30)
    price_paise: int = Field(ge=100, le=100_000_000)
    duration_minutes: int = Field(default=60, ge=5, le=1440)
    active: bool = True


class BookingRequest(BaseModel):
    service_id: str = Field(min_length=1, max_length=40)
    scheduled_for: datetime
    location_text: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=500)
    contact_name: str = Field(min_length=2, max_length=100)
    contact_phone: str = Field(min_length=10, max_length=20)


class BookingStatusRequest(BaseModel):
    status: Literal["confirmed", "completed", "refunded", "cancelled"]
    assigned_uid: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=300)
