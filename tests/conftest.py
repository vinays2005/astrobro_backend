"""Pytest configuration.

The suite is hermetic: it never touches the developer's .env database or keys. Before the app is imported we point
DATABASE_URL at a throw-away SQLite file, blank every external service, and create the tables once.
"""
import asyncio
import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="astrobro-tests-")
# TEST_DATABASE_URL lets the same suite run against a real Postgres (scripts/pg_tests.py); the default is a temp SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or ("sqlite+aiosqlite:///" + _TMP.replace("\\", "/") + "/test.db")
for _name in ("GROQ_API_KEY", "QDRANT_URL", "QDRANT_API_KEY", "API_KEY", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET",
              "RAZORPAY_WEBHOOK_SECRET", "REQUIRE_ID_TOKEN", "ADMIN_EMAILS", "ADMIN_UIDS"):
    os.environ[_name] = ""
os.environ.pop("REQUIRE_ID_TOKEN")      # an empty string is not a valid bool; the default (false) applies
os.environ["DEBUG"] = "false"

from app.database.connection import init_db  # noqa: E402  (must come after the environment is prepared)

asyncio.run(init_db())

# Required for pytest-asyncio auto mode
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Tests share one process: clear the in-memory limiter and any swapped token verifier between tests."""
    from app.security import identity
    from app.security.ratelimit import limiter

    yield
    limiter._hits.clear()
    identity.set_verifier(None)
