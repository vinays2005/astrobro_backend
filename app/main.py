"""AstroBro FastAPI application factory."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.agents.singleton import AIUnavailableError
from app.api.routes_kundli import router as kundli_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.api.routes_books import router as books_router
from app.api.routes_prediction import router as prediction_router
from app.api.routes_payment import router as payment_router
from app.api.routes_report import router as report_router
from app.api.routes_panchang import router as panchang_router
from app.api.routes_horoscope import router as horoscope_router
from app.api.routes_transit import router as transit_router
from app.api.routes_analysis import dasha_router, dosha_router, remedies_router
from app.api.routes_match import match_router, love_router
from app.api.routes_numerology import router as numerology_router
from app.api.routes_tarot import router as tarot_router
from app.api.routes_vastu import router as vastu_router
from app.api.routes_muhurat import router as muhurat_router
from app.api.routes_calendar import router as calendar_router
from app.api.routes_assistant import router as assistant_router
from app.database.connection import init_db

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("astrobro_starting", model=settings.groq_model, env=settings.app_env)
    await init_db()
    logger.info("database_ready")

    # Warm the fixed-astronomy caches once, synchronously (Swiss Ephemeris is not thread-safe),
    # so the first user never pays for them. A failure here must never block startup.
    try:
        from datetime import datetime, timezone
        from app.astrology import calendar_hindu, transits

        year = datetime.now(timezone.utc).year
        transits._saturn_ingresses_all()
        calendar_hindu.events_for_year(year)
        logger.info("astrology_caches_ready", year=year)
    except Exception as exc:
        logger.warning("astrology_warmup_failed", error=str(exc))

    # Pre-load the orchestrator once — avoids reloading the embedding model on every request
    # (was adding 15-25s per call). Calculated endpoints do not need it, so a missing LLM key or an
    # unreachable vector DB must not stop the API from starting: AI routes answer 503 until it is
    # ready, and a background task keeps retrying so a short outage at boot heals itself.
    retry_task: asyncio.Task | None = None
    try:
        from app.agents.orchestrator import AgentOrchestrator
        from app.agents.singleton import set_orchestrator
        set_orchestrator(AgentOrchestrator())
        logger.info("orchestrator_ready")
    except Exception as exc:
        logger.warning("orchestrator_unavailable", error=str(exc), retry_in_s=_ORCHESTRATOR_RETRY_SECONDS)
        retry_task = asyncio.create_task(_retry_orchestrator())

    yield
    if retry_task is not None:
        retry_task.cancel()
    logger.info("astrobro_stopping")


_ORCHESTRATOR_RETRY_SECONDS = 60.0
_ORCHESTRATOR_RETRY_MAX_SECONDS = 600.0


async def _retry_orchestrator() -> None:
    """Keep trying to bring the AI layer up, backing off up to ten minutes between attempts."""
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.singleton import set_orchestrator

    delay = _ORCHESTRATOR_RETRY_SECONDS
    while True:
        await asyncio.sleep(delay)
        try:
            # Built in a worker thread so a slow vector-DB connection never blocks requests.
            set_orchestrator(await asyncio.to_thread(AgentOrchestrator))
            logger.info("orchestrator_ready", after_retry=True)
            return
        except Exception as exc:
            delay = min(delay * 2, _ORCHESTRATOR_RETRY_MAX_SECONDS)
            logger.warning("orchestrator_unavailable", error=str(exc), retry_in_s=delay)


def create_app() -> FastAPI:
    app = FastAPI(
        title="AstroBro AI Backend",
        version="1.0.0",
        description="Deterministic Vedic astrology engine + AI reasoning layer",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    # ── CORS ──────────────────────────────────────────────
    # Dev: allow everything so Flutter web (random port each run) works.
    # Prod: set explicit origins in settings.allowed_origins and set
    #       ALLOW_CREDENTIALS=True in config.
    #
    # IMPORTANT: allow_credentials=True is INVALID with allow_origins=["*"].
    # The browser will reject the response. So we auto-fallback to False
    # whenever a wildcard origin is present.
    origins = list(settings.allowed_origins or [])
    using_wildcard = "*" in origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if using_wildcard else origins,
        allow_credentials=False if using_wildcard else True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Request ID tracing
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AIUnavailableError)
    async def ai_unavailable(request: Request, exc: AIUnavailableError):
        return JSONResponse(
            status_code=503,
            content={
                "error": "ai_unavailable",
                "message": "The AI astrologer is temporarily unavailable. Please try again in a few minutes.",
            },
        )

    # Global error handler — always returns JSON, never crashes
    @app.exception_handler(Exception)
    async def global_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error("unhandled_exception", request_id=request_id, error=str(exc), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again.",
                "request_id": request_id,
            },
        )

    # Routes
    app.include_router(kundli_router)
    app.include_router(chat_router)
    app.include_router(health_router)
    app.include_router(books_router)
    app.include_router(prediction_router)
    app.include_router(payment_router)
    app.include_router(report_router)
    app.include_router(panchang_router)
    for r in (horoscope_router, transit_router, dasha_router, dosha_router, remedies_router, match_router,
              love_router, numerology_router, tarot_router, vastu_router, muhurat_router, calendar_router,
              assistant_router):
        app.include_router(r)

    @app.get("/")
    async def root():
        return {"message": "AstroBro AI Backend", "docs": "/docs"}

    return app


app = create_app()