"""Environment parsing of the list-valued settings (Railway sets them as plain text)."""
from __future__ import annotations

import pytest

from app.config import Settings


@pytest.mark.parametrize("raw,expected", [
    ("", []),
    ("owner@example.com", ["owner@example.com"]),
    ("a@x.com, b@x.com ,c@x.com", ["a@x.com", "b@x.com", "c@x.com"]),
    ('["a@x.com","b@x.com"]', ["a@x.com", "b@x.com"]),
])
def test_admin_emails_accept_commas_or_json(monkeypatch, raw, expected):
    monkeypatch.setenv("ADMIN_EMAILS", raw)
    assert Settings(_env_file=None).admin_emails == expected


def test_allowed_origins_keep_the_format_used_in_production(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", '["*"]')                      # exactly what Railway holds today
    assert Settings(_env_file=None).allowed_origins == ["*"]
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000,https://astrobro.example")
    assert Settings(_env_file=None).allowed_origins == ["http://localhost:3000", "https://astrobro.example"]


def test_secure_defaults(monkeypatch):
    for name in ("ADMIN_EMAILS", "ADMIN_UIDS", "REQUIRE_ID_TOKEN", "FREE_CHATS_PER_DAY"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.admin_emails == [] and s.admin_uids == []              # nobody is an admin until the owner says so
    assert s.require_id_token is False                              # older app versions keep working
    assert s.free_chats_per_day == 10 and s.firebase_project_id == "astro-bro-96380"
