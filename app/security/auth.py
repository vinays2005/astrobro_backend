"""API key authentication dependency for FastAPI routes."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_api_key(x_api_key: str = Header(default="")) -> None:
    """
    FastAPI dependency that enforces X-API-Key header.

    If API_KEY is empty (default dev config), the check is skipped so
    local development works without any config. Set API_KEY in .env / Railway
    env vars to enable protection.
    """
    settings = get_settings()
    if not settings.api_key:
        return  # dev mode — no key configured, allow all

    if not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Pass X-API-Key header.",
        )
