"""Report generation API — free & paid PDF kundali reports.

Auto-approve mode (AUTO_APPROVE_PAYMENTS=True in config):
  • Paid PDF is granted without payment verification.
  • Once Razorpay keys are live, set AUTO_APPROVE_PAYMENTS=False in Railway env vars
    to switch to real payment verification.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import get_settings
from app.security.auth import require_api_key
from app.astrology.engine import AstrologyEngine
from app.services.pdf_generator import generate_report_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/report", tags=["report"])


# ── Request models ────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    name: str
    date_of_birth: str       # "YYYY-MM-DD"
    time_of_birth: str       # "HH:MM"
    latitude: float
    longitude: float
    timezone: float = 5.5
    location_name: str = ""
    tier: str = "free"       # "free" | "paid"
    # Payment fields (required when tier=="paid" and auto_approve==False)
    razorpay_payment_id: str = ""
    razorpay_order_id: str = ""
    razorpay_signature: str = ""


# ── AI text generation ────────────────────────────────────────────────────────

async def _generate_ai_sections(chart: dict, name: str, tier: str) -> dict[str, str]:
    """Call Groq to generate personalised text for paid report sections."""
    if tier != "paid":
        return {}

    try:
        from groq import AsyncGroq
        settings = get_settings()
        if not settings.groq_api_key:
            return {}

        client = AsyncGroq(api_key=settings.groq_api_key)
        planets = chart.get("planets", {})
        asc = chart.get("ascendant", {})
        moon_nakshatra = chart.get("nakshatra_moon", {})
        dasha = chart.get("current_dasha", {})

        # Build concise chart summary for the prompt
        planet_lines = []
        for pname, pinfo in planets.items():
            if isinstance(pinfo, dict):
                planet_lines.append(
                    f"{pname}: {pinfo.get('sign','?')} house {pinfo.get('house','?')} "
                    f"({pinfo.get('dignity','?')}{'R' if pinfo.get('retrograde') else ''})"
                )

        chart_summary = (
            f"Name: {name}\n"
            f"Lagna: {asc.get('sign','?')}\n"
            f"Moon Sign: {planets.get('Moon', {}).get('sign', '?')}\n"
            f"Nakshatra: {moon_nakshatra.get('name','?')} pada {moon_nakshatra.get('pada','?')}\n"
            f"Current Mahadasha: {dasha.get('mahadasha','?')} until {dasha.get('mahadasha_end','?')}\n"
            f"Yogas: {', '.join(chart.get('yogas', []))}\n"
            "Planets:\n" + "\n".join(planet_lines)
        )

        prompt = f"""You are an expert Vedic astrologer. Based on this birth chart, write concise,
personalised paragraphs (3-5 sentences each) for a Jyotish report.

BIRTH CHART:
{chart_summary}

Write ONE paragraph for EACH of these sections (label each with the exact section name):
- Career & Profession
- Health & Wellbeing
- Relationships & Marriage
- Finance & Wealth
- Education & Knowledge
- Family & Domestic Life
- Children & Progeny
- Property & Assets
- Travels & Foreign Connections
- Spirituality & Dharma
- Enemies & Legal Matters
- Longevity & Hidden Matters
- Lucky Profile (colors, day, number, gem, deity)
- Varshaphal (annual prediction for current year)
- Sade Sati (current Saturn position impact)
- Kalsarpa (Kalsarpa Dosh analysis)
- Vedic Remedies (personalised remedies: gemstone, mantra, yantra, puja, charity, fasting — specific to this chart)

Keep each paragraph personal, specific to the chart, and practically useful.
For the Vedic Remedies section write 5-8 sentences covering the most important remedies for this specific chart.
Do NOT use generic filler text."""

        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.6,
        )
        raw = response.choices[0].message.content or ""
        return _parse_ai_sections(raw)

    except Exception as exc:
        logger.warning("ai_sections_failed", error=str(exc))
        return {}


def _parse_ai_sections(raw: str) -> dict[str, str]:
    """Parse labeled paragraphs from AI output into a dict."""
    sections: dict[str, str] = {}
    current_key = None
    current_lines: list[str] = []

    labels = [
        "Career & Profession", "Health & Wellbeing", "Relationships & Marriage",
        "Finance & Wealth", "Education & Knowledge", "Family & Domestic Life",
        "Children & Progeny", "Property & Assets", "Travels & Foreign Connections",
        "Spirituality & Dharma", "Enemies & Legal Matters", "Longevity & Hidden Matters",
        "Lucky Profile", "Varshaphal", "Sade Sati", "Kalsarpa", "Vedic Remedies",
    ]

    for line in raw.splitlines():
        stripped = line.strip()
        matched = next((lbl for lbl in labels if stripped.startswith(lbl)), None)
        if matched:
            if current_key and current_lines:
                sections[current_key] = " ".join(current_lines).strip()
            current_key = matched
            rest = stripped[len(matched):].lstrip(":- ").strip()
            current_lines = [rest] if rest else []
        elif current_key:
            current_lines.append(stripped)

    if current_key and current_lines:
        sections[current_key] = " ".join(current_lines).strip()

    return sections


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    dependencies=[Depends(require_api_key)],
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def generate_report(body: ReportRequest) -> Response:
    """Generate a free or paid PDF kundali report.

    Paid tier logic:
      - If AUTO_APPROVE_PAYMENTS=True  → skip payment, generate PDF immediately.
      - If AUTO_APPROVE_PAYMENTS=False → verify Razorpay signature first.
    """
    settings = get_settings()

    # ── Payment gate ──────────────────────────────────────────────────────────
    if body.tier == "paid":
        if not settings.auto_approve_payments:
            # Require valid Razorpay fields
            if not body.razorpay_payment_id or not body.razorpay_order_id or not body.razorpay_signature:
                raise HTTPException(status_code=402, detail="Payment required")

            secret = settings.razorpay_key_secret
            if not secret:
                raise HTTPException(status_code=503, detail="Payment service not configured")

            payload = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
            expected = hmac.new(
                secret.encode(),
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(expected, body.razorpay_signature):
                raise HTTPException(status_code=400, detail="Invalid payment signature")

    # ── Calculate chart ───────────────────────────────────────────────────────
    try:
        engine = AstrologyEngine()
        dt = datetime.fromisoformat(f"{body.date_of_birth}T{body.time_of_birth}:00")
        chart_obj = engine.calculate_chart(
            dt=dt,
            lat=body.latitude,
            lon=body.longitude,
            tz=body.timezone,
        )
        # Serialise to plain dict so pdf_generator can use it
        chart: dict = {
            "ascendant": {"sign": chart_obj.ascendant.sign if hasattr(chart_obj.ascendant, "sign") else str(chart_obj.ascendant)},
            "planets": {
                k: {
                    "sign": p.sign, "house": p.house, "degree": p.sign_degree,
                    "nakshatra": p.nakshatra, "nakshatra_lord": p.nakshatra_lord,
                    "retrograde": p.retrograde, "combust": p.combust,
                    "dignity": p.dignity,
                }
                for k, p in chart_obj.planets.items()
            },
            "nakshatra_moon": {
                "name": chart_obj.nakshatra_moon.name,
                "pada": chart_obj.nakshatra_moon.pada,
                "lord": chart_obj.nakshatra_moon.lord,
            },
            "yogas": chart_obj.yogas,
            "current_dasha": chart_obj.current_dasha,
        }
    except Exception as exc:
        logger.error("chart_calculation_failed", error=str(exc))
        raise HTTPException(status_code=400, detail=f"Chart calculation failed: {exc}") from exc

    # ── AI text sections (paid only) ──────────────────────────────────────────
    ai_sections = await _generate_ai_sections(chart, body.name, body.tier)

    # ── Generate PDF ──────────────────────────────────────────────────────────
    try:
        pdf_bytes = generate_report_pdf(
            tier=body.tier,
            name=body.name,
            dob=body.date_of_birth,
            tob=body.time_of_birth,
            location=body.location_name or f"{body.latitude:.2f}N, {body.longitude:.2f}E",
            chart=chart,
            ai_sections=ai_sections,
        )
    except Exception as exc:
        logger.error("pdf_generation_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="PDF generation failed") from exc

    filename = f"AstroBro_{body.name.replace(' ', '_')}_{body.tier}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
