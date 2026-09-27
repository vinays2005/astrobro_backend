"""
API request/response Pydantic schemas.
These form the contract with the Flutter frontend.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── Requests ──────────────────────────────────────────────────────────────────

class BirthData(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: str = Field(..., description="YYYY-MM-DD")
    time_of_birth: str = Field(default="12:00", description="HH:MM (24h)")
    timezone: str = Field(default="Asia/Kolkata", examples=["Asia/Kolkata", "America/New_York"])
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    gender: Literal["male", "female", "other"] | None = None
    language: str = Field(default="english")

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        # Fails loud — no silent coercions
        datetime.fromisoformat(v)
        return v

    @field_validator("time_of_birth")
    @classmethod
    def validate_tob(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) < 2 or not all(p.isdigit() for p in parts):
            raise ValueError("time_of_birth must be HH:MM")
        return v


class KundliRequest(BirthData):
    ayanamsa: str = Field(default="LAHIRI")


class PredictionRequest(BaseModel):
    birth_data: BirthData
    topic: Literal[
        "career", "marriage", "finance", "education", "health",
        "children", "property", "travel", "spirituality", "general"
    ]


class ChatRequest(BaseModel):
    birth_data: BirthData | None = None
    kundli_id: str | None = None
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_history: list[dict] = Field(default_factory=list)
    language: str = Field(default="english")


class BookIngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    author: str | None = None
    topic_tags: list[str] = Field(default_factory=list)


# ── Responses ─────────────────────────────────────────────────────────────────

class PlanetInfo(BaseModel):
    sign: str
    degree: float
    house: int
    nakshatra: str
    nakshatra_pada: int
    nakshatra_lord: str
    retrograde: bool
    combust: bool
    dignity: str
    dignity_score: float


class HouseInfo(BaseModel):
    number: int
    sign: str
    lord: str
    occupants: list[str]


class DashaInfo(BaseModel):
    lord: str | None
    start: str | None
    end: str | None


class KundliResponse(BaseModel):
    name: str
    ascendant: dict
    planets: dict[str, PlanetInfo]
    houses: list[HouseInfo]
    nakshatra_moon: dict
    yogas: list[dict]
    current_dasha: dict


class PredictionFactor(BaseModel):
    factor: str
    observation: str
    impact: Literal["supportive", "challenging", "mixed", "neutral"]
    evidence: list[str] = []


class TimePeriod(BaseModel):
    start: str
    end: str
    interpretation: str


class AstrologySource(BaseModel):
    book: str
    page: int | str | None = None  # LLM sometimes emits "Unknown" — accept str too
    text: str | None = None


class PredictionResponse(BaseModel):
    request_id: str
    topic: str
    summary: str
    analysis: list[PredictionFactor] = []
    time_periods: list[TimePeriod] = []
    sources: list[AstrologySource] = []
    confidence: float = 0.5
    disclaimer: str = (
        "Vedic astrology interpretation based on classical principles. "
        "Not a substitute for professional medical, legal, or financial advice."
    )
    errors: list[str] = []


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    topic: str | None = None
    sources: list[AstrologySource] = []
    follow_up_questions: list[str] = []
    disclaimer: str = ""
    errors: list[str] = []


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    ollama_connected: bool = False
    vector_db_chunks: int = 0