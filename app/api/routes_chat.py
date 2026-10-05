"""AI chat routes — SSE streaming + regular response.

Every call is charged against the signed-in user's daily allowance on the server (app/services/metering.py), and
given back if the AI fails, so the limit cannot be bypassed by editing the app."""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from groq import APIStatusError

from app.agents.singleton import get_orchestrator
from app.models.api import ChatRequest, ChatResponse
from app.security.auth import require_api_key
from app.security.identity import AuthUser, ai_user
from app.services.metering import charge_ai_call, refund_ai_call

logger = structlog.get_logger()
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat(request: ChatRequest, http: Request, user: AuthUser | None = Depends(ai_user)) -> dict:
    """Single-turn AI astrology chat."""
    orchestrator = get_orchestrator()
    meter = await charge_ai_call(user, http)
    try:
        return await orchestrator.run(
            user_input=request.question,
            birth_data=request.birth_data.model_dump() if request.birth_data else None,
            conversation_history=request.conversation_history,
            force_chat=True,
            language=request.language,
        )
    except APIStatusError as exc:
        await refund_ai_call(meter)
        # Provider rate/size limits: keep details (org id, quotas) server-side.
        logger.error("chat_llm_error", status=exc.status_code, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="The AI service is busy right now. Please try again in a minute.",
        ) from exc
    except Exception:
        await refund_ai_call(meter)
        raise


@router.post("/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(request: ChatRequest, http: Request, user: AuthUser | None = Depends(ai_user)) -> StreamingResponse:
    """
    Streaming AI astrology chat — true SSE token stream from Groq.

    Tokens arrive at the client within ~1s (RAG lookup + first LLM token),
    instead of the old approach that ran the full 2-minute pipeline first
    and only then fake-streamed words — causing 499 client timeouts.
    """
    orchestrator = get_orchestrator()
    meter = await charge_ai_call(user, http)

    async def event_generator():
        import uuid as _uuid
        request_id = str(_uuid.uuid4())
        yield f"data: {json.dumps({'type': 'start', 'request_id': request_id})}\n\n"

        try:
            full_text = ""
            async for token in orchestrator.run_chat_stream(
                user_input=request.question,
                birth_data=request.birth_data.model_dump() if request.birth_data else None,
                conversation_history=request.conversation_history,
                language=request.language,
            ):
                full_text += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # Wrap plain text in the structure Flutter's done handler expects.
            # full_text is now plain prose (CHAT_STREAM_PROMPT), not JSON.
            done_payload = {
                "type": "done",
                "request_id": request_id,
                "answer": full_text,
                "full": {"answer": full_text, "topic": "general", "follow_up_questions": []},
            }
            yield f"data: {json.dumps(done_payload)}\n\n"

        except Exception as exc:
            logger.error("chat_stream_failed", request_id=request_id, error=str(exc))
            await refund_ai_call(meter)
            message = (
                "The AI service is busy right now. Please try again in a minute."
                if isinstance(exc, APIStatusError)
                else "Something went wrong. Please try again."
            )
            yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
