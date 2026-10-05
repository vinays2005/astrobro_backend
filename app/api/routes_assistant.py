"""Assistant APIs: concern routing, voice input, notification feed, languages and the feature catalogue."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.common import chart_from_birth, utc_now, valid_tz
from app.astrology import ephem as E
from app.astrology import intent as IN
from app.astrology import notifications as NF
from app.models.features import IntentRequest, NotificationFeedRequest
from app.security.auth import require_api_key
from app.services import features_catalog, languages, speech

router = APIRouter(tags=["assistant"], dependencies=[Depends(require_api_key)])


@router.post("/api/intent/classify")
async def classify_intent(req: IntentRequest) -> dict:
    """Which kind of concern is this, and which module or astrologer specialty fits?"""
    return IN.classify(req.text)


@router.get("/api/intent/categories")
async def intent_categories() -> dict:
    return {"categories": IN.categories()}


@router.post("/api/voice/transcribe")
async def transcribe_voice(file: UploadFile = File(...), language: str | None = Form(None)) -> dict:
    """Speech to text for voice questions. Send the transcript to /api/chat to get an answer."""
    data = await file.read()
    try:
        return await speech.transcribe(data, file.filename or "audio.m4a", language)
    except speech.SpeechError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from None


@router.post("/api/notifications/feed")
async def notification_feed(req: NotificationFeedRequest) -> dict:
    """Upcoming personal and calendar events (daily horoscope, dasha changes, transits, festivals, birthday)."""
    valid_tz(req.timezone)
    b = req.birth_data
    chart = chart_from_birth(b)
    start = req.start_date or utc_now().astimezone(E.tzinfo(req.timezone)).date()
    return NF.build_feed(
        chart, req.name or b.name, date.fromisoformat(b.date_of_birth), start, req.days,
        req.latitude if req.latitude is not None else b.latitude,
        req.longitude if req.longitude is not None else b.longitude,
        req.timezone, utc_now(),
    )


@router.get("/api/languages")
async def list_languages() -> dict:
    return {"languages": languages.LANGUAGES,
            "note": "AI answer quality varies by language. Calculated content is currently English only."}


@router.get("/api/features")
async def features() -> dict:
    return features_catalog.catalogue()
