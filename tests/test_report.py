"""Regression tests for the PDF report pipeline (free tier needs no LLM)."""
from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient, ASGITransport

from app.api.routes_report import _flat_dasha, _parse_ai_sections
from app.astrology.engine import AstrologyEngine
from app.main import app
from app.security.auth import require_api_key


async def _no_auth() -> None:
    return


@pytest.fixture
async def client():
    app.dependency_overrides[require_api_key] = _no_auth
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=60
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


class TestTimezoneOffset:
    def test_numeric_offset_matches_named_zone(self):
        # Report endpoint sends 5.5; it used to silently fall back to UTC (wrong Lagna).
        engine = AstrologyEngine()
        dt = datetime(1990, 8, 15, 14, 30)
        named = engine.calculate_chart(dt=dt, lat=19.076, lon=72.8777, tz="Asia/Kolkata")
        offset = engine.calculate_chart(dt=dt, lat=19.076, lon=72.8777, tz=5.5)
        assert offset.ascendant["sign"] == named.ascendant["sign"] == "Scorpio"


class TestParseAiSections:
    def test_plain_labels(self):
        out = _parse_ai_sections("Career & Profession\nStrong 10th house.\nHealth & Wellbeing\nGood vitality.")
        assert out["Career & Profession"] == "Strong 10th house."
        assert out["Health & Wellbeing"] == "Good vitality."

    def test_markdown_headings_and_bold(self):
        raw = (
            "**Career & Profession**  \nA **strong** 10th house.\n\n"
            "### 2. Lucky Profile (colors, day, number, gem, deity)\nWear red.\n"
        )
        out = _parse_ai_sections(raw)
        assert out["Career & Profession"] == "A strong 10th house."
        assert out["Lucky Profile"] == "Wear red."


class TestFlatDasha:
    def test_flattens_nested_periods(self):
        nested = {
            "mahadasha": {"lord": "Jupiter", "start": "2014-12-20T00:00:00", "end": "2030-12-20T17:35:44"},
            "antardasha": {"lord": "Moon", "start": "x", "end": "y"},
        }
        assert _flat_dasha(nested) == {
            "mahadasha": "Jupiter",
            "antardasha": "Moon",
            "mahadasha_end": "2030-12-20",
        }

    def test_empty(self):
        assert _flat_dasha({})["mahadasha"] == "-"


_FREE_REPORT = {
    "name": "Test User",
    "date_of_birth": "1990-08-15",
    "time_of_birth": "14:30",
    "latitude": 19.076,
    "longitude": 72.8777,
    "timezone": 5.5,
    "location_name": "Mumbai",
    "tier": "free",
}


class TestFreeReportEndpoint:
    async def test_free_report_returns_pdf(self, client: AsyncClient):
        r = await client.post("/api/report/generate", json=_FREE_REPORT)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")

    async def test_free_report_content_is_correct(self, client: AsyncClient):
        fitz = pytest.importorskip("fitz")  # PyMuPDF, optional: reads the text back
        r = await client.post("/api/report/generate", json=_FREE_REPORT)
        text = "".join(p.get_text() for p in fitz.open(stream=r.content, filetype="pdf"))
        assert "Scorpio" in text          # correct Lagna for an IST birth time
        assert "{'sign'" not in text      # no raw dict repr leaking into the report
