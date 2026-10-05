"""Who is calling: verify the Firebase Auth ID token the app sends as `Authorization: Bearer <token>`.

The API key only says "this is some copy of the AstroBro app" and ships inside every APK, so anyone can pull it
out. A Firebase ID token identifies one signed-in user and is signed by Google, which lets the server meter chats,
grant premium, hold wallets and run consultations per user without trusting the app.

Tokens are checked against Google's public signing keys (cached, refreshed when a new key id appears), so no
service-account secret is needed. In soft mode (REQUIRE_ID_TOKEN=false) a request without a token is still accepted
for routes that allow it, which keeps older app versions working.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import jwt
import structlog
from cryptography import x509
from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings

logger = structlog.get_logger()

CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
_DEFAULT_KEY_TTL = 3600.0
_STALE_KEY_GRACE = 24 * 3600.0       # keep using the last good keys this long if Google cannot be reached
_MIN_REFRESH_GAP = 60.0              # an unknown key id triggers at most one refresh a minute


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: str | None
    email_verified: bool
    name: str | None
    is_admin: bool


class TokenError(Exception):
    """The token is missing, malformed, expired, for another project or not signed by Google."""


KeyFetcher = Callable[[], Awaitable[tuple[dict[str, str], float]]]


async def _download_certs() -> tuple[dict[str, str], float]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(CERTS_URL)
        resp.raise_for_status()
    match = re.search(r"max-age=(\d+)", resp.headers.get("cache-control", ""))
    return resp.json(), float(match.group(1)) if match else _DEFAULT_KEY_TTL


class FirebaseTokenVerifier:
    def __init__(self, project_id: str, fetch_certs: KeyFetcher | None = None, clock: Callable[[], float] = time.time):
        self.project_id = project_id
        self._fetch = fetch_certs or _download_certs
        self._clock = clock
        self._keys: dict[str, object] = {}
        self._fresh_until = 0.0
        self._last_refresh = float("-inf")
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        async with self._lock:
            now = self._clock()
            if now - self._last_refresh < _MIN_REFRESH_GAP and self._keys:
                return
            self._last_refresh = now
            try:
                certs, ttl = await self._fetch()
                self._keys = {kid: x509.load_pem_x509_certificate(pem.encode()).public_key() for kid, pem in certs.items()}
                self._fresh_until = now + ttl
            except Exception as exc:  # keep serving with the keys we already have
                logger.warning("firebase_keys_refresh_failed", error=str(exc))
                if not self._keys or now > self._fresh_until + _STALE_KEY_GRACE:
                    self._keys = {}
                    raise TokenError("Cannot load Google's signing keys right now") from exc

    async def _key_for(self, kid: str | None) -> object:
        if not kid:
            raise TokenError("Token has no key id")
        if not self._keys or self._clock() >= self._fresh_until or kid not in self._keys:
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise TokenError("Token was signed with an unknown key")
        return key

    async def verify(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenError("Malformed token") from exc
        if header.get("alg") != "RS256":
            raise TokenError("Unexpected token algorithm")
        key = await self._key_for(header.get("kid"))
        try:
            claims = jwt.decode(
                token, key=key, algorithms=["RS256"], audience=self.project_id,
                issuer=f"https://securetoken.google.com/{self.project_id}", leeway=10,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError(str(exc)) from exc
        uid = claims.get("sub")
        if not isinstance(uid, str) or not uid or len(uid) > 128:
            raise TokenError("Token has no valid subject")
        return claims


_verifier: FirebaseTokenVerifier | None = None


def get_verifier() -> FirebaseTokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = FirebaseTokenVerifier(get_settings().firebase_project_id)
    return _verifier


def set_verifier(verifier: FirebaseTokenVerifier | None) -> None:
    """Swap the verifier (used by tests)."""
    global _verifier
    _verifier = verifier


def _is_admin(uid: str, email: str | None, email_verified: bool) -> bool:
    s = get_settings()
    if uid in s.admin_uids:
        return True
    return bool(email and email_verified and email.lower() in {e.lower() for e in s.admin_emails})


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def optional_user(authorization: str | None = Header(default=None)) -> AuthUser | None:
    """The signed-in user, or None when no token was sent. A token that is sent but invalid is rejected."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Malformed Authorization header")
    try:
        claims = await get_verifier().verify(token.strip())
    except TokenError as exc:
        logger.info("id_token_rejected", reason=str(exc))
        raise _unauthorized("Your sign-in has expired or is invalid. Please sign in again.") from None
    email = claims.get("email")
    verified = bool(claims.get("email_verified"))
    return AuthUser(uid=claims["sub"], email=email, email_verified=verified, name=claims.get("name"),
                    is_admin=_is_admin(claims["sub"], email, verified))


async def current_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser:
    """A signed-in user is required (money, wallet, consultations)."""
    if user is None:
        raise _unauthorized("Please sign in to use this feature.")
    return user


async def ai_user(user: AuthUser | None = Depends(optional_user)) -> AuthUser | None:
    """For AI routes: in strict mode (REQUIRE_ID_TOKEN=true) a signed-in user is required."""
    if user is None and get_settings().require_id_token:
        raise _unauthorized("Please sign in to use this feature.")
    return user


async def admin_user(user: AuthUser = Depends(current_user)) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only.")
    return user
