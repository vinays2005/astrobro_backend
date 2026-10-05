"""Tarot API: deck, spreads, draws, card of the day and optional AI interpretation."""
from __future__ import annotations

from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.astrology import tarot as TR
from app.models.features import TarotDrawRequest
from app.security.auth import require_api_key

logger = structlog.get_logger()
router = APIRouter(prefix="/api/tarot", tags=["tarot"], dependencies=[Depends(require_api_key)])


@router.get("/spreads")
async def spreads() -> dict:
    return {"spreads": [{"key": k, "positions": v, "cards": len(v)} for k, v in TR.SPREADS.items()]}


@router.get("/cards")
async def cards(arcana: str | None = Query(None, pattern="^(major|minor)$"), suit: str | None = None) -> dict:
    out = [c for c in TR.DECK if (not arcana or c["arcana"] == arcana)
           and (not suit or (c["suit"] or "").lower() == suit.lower())]
    return {"count": len(out), "cards": out}


@router.get("/cards/{card_id}")
async def card(card_id: str) -> dict:
    found = TR.get_card(card_id)
    if not found:
        raise HTTPException(status_code=404, detail="Card not found")
    return found


@router.get("/daily")
async def daily(user_key: str = Query("", max_length=100), on: date | None = Query(None, alias="date")) -> dict:
    """Card of the day: the same card all day for the same user key."""
    return TR.card_of_the_day(on or date.today(), user_key)


async def _ai_interpretation(result: dict, language: str) -> str | None:
    """Optional short AI reading of the drawn cards; never raises."""
    try:
        from app.agents.singleton import get_orchestrator
        from app.llm.prompts import system_prompt

        cards_text = "\n".join(
            f"- {r['position']}: {r['card']['name']} ({r['orientation']}) - {r['meaning']}" for r in result["readings"])
        prompt = (
            "You are a thoughtful tarot reader. Using ONLY the cards below, write a warm, balanced reading of 4-6 sentences "
            "that connects the cards to the question. Do not predict certain events, and do not give medical, legal or "
            f"financial advice.\n\nQuestion: {result.get('question') or 'General guidance'}\nSpread: {result['spread']}\n"
            f"Cards:\n{cards_text}\n\nPlain text only."
        )
        llm = get_orchestrator()._llm
        text = await llm.generate(prompt, system=system_prompt(language, json_output=False), temperature=0.6, max_tokens=500)
        return text.strip() or None
    except Exception as exc:
        logger.warning("tarot_ai_failed", error=str(exc))
        return None


@router.post("/draw")
async def draw(req: TarotDrawRequest) -> dict:
    try:
        result = TR.draw(req.spread, req.question, req.seed, req.allow_reversed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if req.interpret:
        result["ai_interpretation"] = await _ai_interpretation(result, req.language)
    return result
