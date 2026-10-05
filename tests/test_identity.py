"""Firebase ID token verification and the user dependencies built on it."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.security import identity
from app.security.auth import require_api_key
from tests.firebase_helpers import KEY, KID, OTHER_KEY, PROJECT, bearer, certificate_pem, install_verifier, make_token


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def uid() -> str:
    return "u-" + uuid.uuid4().hex[:12]


class TestVerifier:
    async def test_accepts_a_valid_token(self):
        verifier, _ = install_verifier()
        claims = await verifier.verify(make_token("abc"))
        assert claims["sub"] == "abc" and claims["email"] == "user@example.com"

    @pytest.mark.parametrize("kwargs", [
        {"expires_in": -60},                                           # expired
        {"audience": "some-other-project"},                            # minted for another Firebase project
        {"issuer": "https://securetoken.google.com/some-other"},       # wrong issuer
        {"key": OTHER_KEY},                                            # signed by someone else
    ])
    async def test_rejects_bad_tokens(self, kwargs):
        verifier, _ = install_verifier()
        with pytest.raises(identity.TokenError):
            await verifier.verify(make_token(**kwargs))

    async def test_rejects_garbage_and_missing_key_id(self):
        verifier, _ = install_verifier()
        for token in ("not-a-token", "a.b.c", ""):
            with pytest.raises(identity.TokenError):
                await verifier.verify(token)
        with pytest.raises(identity.TokenError):
            await verifier.verify(make_token(kid="unknown"))

    async def test_rejects_the_alg_none_and_hmac_tricks(self):
        verifier, _ = install_verifier()
        unsigned = jwt.encode({"sub": "x", "aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}",
                               "iat": 1, "exp": 4102444800}, key="", algorithm="none", headers={"kid": KID})
        with pytest.raises(identity.TokenError):
            await verifier.verify(unsigned)
        # The classic key-confusion attack: sign with HS256 using the public certificate text as the secret.
        # PyJWT refuses to build such a token, so assemble it by hand.
        def b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        body = b64(json.dumps({"sub": "x", "aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}",
                               "iat": 1, "exp": 4102444800}).encode())
        mac = hmac.new(certificate_pem().encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        with pytest.raises(identity.TokenError):
            await verifier.verify(f"{head}.{body}.{b64(mac)}")

    async def test_requires_a_subject(self):
        verifier, _ = install_verifier()
        token = jwt.encode({"aud": PROJECT, "iss": f"https://securetoken.google.com/{PROJECT}", "iat": 1, "exp": 4102444800},
                           KEY, algorithm="RS256", headers={"kid": KID})
        with pytest.raises(identity.TokenError):
            await verifier.verify(token)

    async def test_keys_are_cached_between_requests(self):
        verifier, state = install_verifier()
        for _ in range(5):
            await verifier.verify(make_token())
        assert state["fetches"] == 1

    async def test_a_new_key_id_triggers_one_refresh_not_a_flood(self):
        verifier, state = install_verifier()
        await verifier.verify(make_token())
        for _ in range(4):
            with pytest.raises(identity.TokenError):
                await verifier.verify(make_token(kid="rotated"))
        assert state["fetches"] == 1                                  # throttled: unknown ids cannot hammer Google

    async def test_key_rotation_is_picked_up(self):
        verifier, state = install_verifier()
        await verifier.verify(make_token())
        verifier._last_refresh = float("-inf")                       # as if a minute has passed
        state["certs"] = {KID: certificate_pem(), "rotated": certificate_pem()}
        assert (await verifier.verify(make_token(kid="rotated")))["sub"] == "user-1"

    async def test_cached_keys_survive_google_being_unreachable(self):
        verifier, state = install_verifier(ttl=0.0)                  # always considered stale
        await verifier.verify(make_token())
        verifier._last_refresh = float("-inf")
        state["fail"] = True
        assert (await verifier.verify(make_token()))["sub"] == "user-1"

    async def test_no_keys_and_no_network_means_rejection(self):
        verifier, state = install_verifier()
        state["fail"] = True
        with pytest.raises(identity.TokenError):
            await verifier.verify(make_token())


class TestDependencies:
    async def test_me_requires_sign_in(self, client):
        install_verifier()
        r = await client.get("/api/me")
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"

    async def test_bad_headers_are_rejected_not_ignored(self, client):
        install_verifier()
        for header in ("Basic abc", "Bearer", "Bearer    ", "token abc"):
            assert (await client.get("/api/me", headers={"Authorization": header})).status_code == 401
        r = await client.get("/api/me", headers={"Authorization": "Bearer " + make_token(expires_in=-100)})
        assert r.status_code == 401 and "sign in again" in r.json()["detail"].lower()

    async def test_valid_token_identifies_the_user(self, client):
        install_verifier()
        who = uid()
        r = await client.get("/api/me", headers=bearer(who))
        assert r.status_code == 200 and r.json()["uid"] == who and r.json()["plan"] == "free"

    async def test_admin_by_verified_email_or_uid(self, client, monkeypatch):
        install_verifier()
        settings = get_settings()
        monkeypatch.setattr(settings, "admin_emails", ["Owner@Example.com"])
        monkeypatch.setattr(settings, "admin_uids", ["uid-admin"])
        assert (await client.get("/api/me", headers=bearer(uid(), email="owner@example.com"))).json()["is_admin"] is True
        assert (await client.get("/api/me", headers=bearer(uid(), email="owner@example.com", verified=False))).json()["is_admin"] is False
        assert (await client.get("/api/me", headers=bearer("uid-admin", email=None))).json()["is_admin"] is True
        assert (await client.get("/api/me", headers=bearer(uid(), email="other@example.com"))).json()["is_admin"] is False

    async def test_strict_mode_requires_a_token_on_ai_routes(self, monkeypatch):
        install_verifier()
        monkeypatch.setattr(get_settings(), "require_id_token", True)
        with pytest.raises(identity.HTTPException) as err:
            await identity.ai_user(user=None)
        assert err.value.status_code == 401
        monkeypatch.setattr(get_settings(), "require_id_token", False)
        assert await identity.ai_user(user=None) is None

    async def test_admin_routes_reject_normal_users(self):
        user = identity.AuthUser(uid="x", email=None, email_verified=False, name=None, is_admin=False)
        with pytest.raises(identity.HTTPException) as err:
            await identity.admin_user(user=user)
        assert err.value.status_code == 403
