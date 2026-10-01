"""AstroBro FastAPI application factory."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api.routes_kundli import router as kundli_router
from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.api.routes_books import router as books_router
from app.api.routes_prediction import router as prediction_router
from app.api.routes_payment import router as payment_router
from app.api.routes_report import router as report_router
from app.database.connection import init_db

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("astrobro_starting", model=settings.groq_model, env=settings.app_env)
    await init_db()
    logger.info("database_ready")

    # Pre-load the orchestrator once — avoids reloading SentenceTransformer
    # and CrossEncoder on every request (was adding 15-25s per call).
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.singleton import set_orchestrator
    set_orchestrator(AgentOrchestrator())
    logger.info("orchestrator_ready")

    yield
    logger.info("astrobro_stopping")


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

    @app.get("/")
    async def root():
        return {"message": "AstroBro AI Backend", "docs": "/docs"}

    return app


app = create_app()