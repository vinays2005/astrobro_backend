"""Helpers for tests that need signed-in users: an RSA key, a matching X.509 certificate, and Firebase-style tokens."""
from __future__ import annotations

import datetime as dt
import time

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.security.identity import FirebaseTokenVerifier, set_verifier

PROJECT = "astro-bro-test"
KID = "test-key-1"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def certificate_pem(private_key=KEY) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(private_key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def make_token(uid: str = "user-1", *, email: str | None = "user@example.com", verified: bool = True,
               name: str | None = "Test User", expires_in: int = 3600, project: str = PROJECT, kid: str = KID,
               audience: str | None = None, issuer: str | None = None, key=KEY, algorithm: str = "RS256") -> str:
    now = int(time.time())
    claims = {
        "sub": uid, "aud": audience or project, "iss": issuer or f"https://securetoken.google.com/{project}",
        "iat": now - 5, "exp": now + expires_in, "auth_time": now - 5,
    }
    if email:
        claims.update({"email": email, "email_verified": verified})
    if name:
        claims["name"] = name
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def install_verifier(certs: dict[str, str] | None = None, ttl: float = 3600.0) -> tuple[FirebaseTokenVerifier, dict]:
    """Make the app trust tokens signed with KEY. Returns the verifier and a dict counting key downloads."""
    state = {"fetches": 0, "certs": certs if certs is not None else {KID: certificate_pem()}, "fail": False}

    async def fetch():
        state["fetches"] += 1
        if state["fail"]:
            raise RuntimeError("google unreachable")
        return state["certs"], ttl

    verifier = FirebaseTokenVerifier(PROJECT, fetch_certs=fetch)
    set_verifier(verifier)
    return verifier, state


def bearer(uid: str = "user-1", **kw) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(uid, **kw)}"}
