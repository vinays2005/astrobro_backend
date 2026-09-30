"""AI chat routes — SSE streaming + regular response."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agents.singleton import get_orchestrator
from app.models.api import ChatRequest, ChatResponse
from app.security.auth import require_api_key

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat(request: ChatRequest) -> dict:
    """Single-turn AI astrology chat."""
    orchestrator = get_orchestrator()
    result = await orchestrator.run(
        user_input=request.question,
        birth_data=request.birth_data.model_dump() if request.birth_data else None,
        conversation_history=request.conversation_history,
        force_chat=True,
    )
    return result


@router.post("/stream", dependencies=[Depends(require_api_key)])
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    Streaming AI astrology chat — sends chunks as Server-Sent Events.
    Flutter uses http streaming to receive tokens in real-time.
    """
    orchestrator = get_orchestrator()

    async def event_generator():
        # Send start event
        yield f"data: {json.dumps({'type': 'start', 'request_id': 'pending'})}\n\n"

        try:
            # Full pipeline first to get chart + context
            result = await orchestrator.run(
                user_input=request.question,
                birth_data=request.birth_data.model_dump() if request.birth_data else None,
                conversation_history=request.conversation_history,
                force_chat=True,
            )
            answer = result.get("answer", "")
            # Stream answer token by token (word level)
            words = answer.split()
            buffer = ""
            for i, word in enumerate(words):
                buffer += word + " "
                if i % 3 == 2 or i == len(words) - 1:
                    yield f"data: {json.dumps({'type': 'token', 'content': buffer})}\n\n"
                    buffer = ""

            # Send complete event with full result
            yield f"data: {json.dumps({'type': 'done', 'full': result})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )