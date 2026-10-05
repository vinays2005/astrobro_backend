"""Request schemas for the feature endpoints (horoscope, transits, dasha, matching, numerology, tarot, ...)."""
from __future__ import annotations

from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field

from app.models.api import BirthData

Period = Literal["today", "tomorrow", "daily", "weekly", "monthly", "yearly"]


class PersonalHoroscopeRequest(BaseModel):
    birth_data: BirthData
    period: Period = "today"
    date: Date | None = None
    tz: str = "Asia/Kolkata"


class NatalTransitRequest(BaseModel):
    birth_data: BirthData
    date: Date | None = None
    tz: str = "Asia/Kolkata"


class BirthOnlyRequest(BaseModel):
    birth_data: BirthData


class DashaRequest(BaseModel):
    birth_data: BirthData
    depth: Literal["maha", "antar", "praty"] = "antar"
    years_ahead: int = Field(default=30, ge=1, le=120)
    include_interpretation: bool = True


class DoshaRequest(BaseModel):
    birth_data: BirthData
    include_remedies: bool = True


class DetailedMatchRequest(BaseModel):
    person1: BirthData
    person2: BirthData
    person1_role: Literal["groom", "bride"] = "groom"


class LoveRequest(BaseModel):
    name1: str = Field(..., min_length=1, max_length=60)
    name2: str = Field(..., min_length=1, max_length=60)
    birth1: BirthData | None = None
    birth2: BirthData | None = None


class NumerologyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: Date
    date: Date | None = None


class NumerologyPerson(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: Date


class NumerologyCompatibilityRequest(BaseModel):
    person1: NumerologyPerson
    person2: NumerologyPerson


class TarotDrawRequest(BaseModel):
    spread: str = "three_card"
    question: str | None = Field(default=None, max_length=300)
    seed: str | int | None = Field(default=None)
    allow_reversed: bool = True
    interpret: bool = False
    language: str = "english"


class VastuRequest(BaseModel):
    entrance_facing: str | None = None
    rooms: dict[str, str] = Field(default_factory=dict, max_length=25)


class MuhuratRequest(BaseModel):
    event: str
    start_date: Date
    end_date: Date
    latitude: float = Field(default=28.6139, ge=-90, le=90)
    longitude: float = Field(default=77.2090, ge=-180, le=180)
    timezone: str = "Asia/Kolkata"
    relaxed: bool = False
    include_excluded: bool = False


class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class NotificationFeedRequest(BaseModel):
    birth_data: BirthData
    name: str | None = Field(default=None, max_length=100)
    start_date: Date | None = None
    days: int = Field(default=14, ge=1, le=60)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = "Asia/Kolkata"
