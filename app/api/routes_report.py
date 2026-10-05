"""Report generation API — free & paid PDF kundali reports.

The paid PDF is included with premium plans and otherwise sold per report through /api/billing.
AUTO_APPROVE_PAYMENTS=True (development only) hands it out without any payment.
"""
from __future__ import annotations

import re
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import get_settings
from app.database.connection import session_scope
from app.security.auth import require_api_key
from app.security.identity import AuthUser, ai_user
from app.astrology.engine import AstrologyEngine
from app.services import accounts, billing
from app.services.pdf_generator import generate_report_pdf

logger = structlog.get_logger()
router = APIRouter(prefix="/api/report", tags=["report"])

_MD_LEAD = re.compile(r"^[\s#>*_\-]*(?:\d+[.)]\s*)?[*_]*")


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


def _asc_sign(asc: object) -> str:
    if isinstance(asc, dict):
        return str(asc.get("sign", "-"))
    return str(getattr(asc, "sign", asc))


def _flat_dasha(dasha: dict) -> dict:
    """Engine returns nested {lord,start,end} periods; PDF/AI code wants flat strings."""
    def lord(p: object) -> str:
        return str(p.get("lord", "-")) if isinstance(p, dict) else str(p or "-")

    maha = dasha.get("mahadasha")
    end = maha.get("end", "") if isinstance(maha, dict) else dasha.get("mahadasha_end", "")
    return {
        "mahadasha": lord(maha),
        "antardasha": lord(dasha.get("antardasha")),
        "mahadasha_end": str(end)[:10] or "-",
    }


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
            model=settings.groq_report_model,
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
        # Models wrap headings in markdown ("**Career & Profession**", "### 1. ...")
        plain = _MD_LEAD.sub("", line.strip()).replace("**", "")
        matched = next((lbl for lbl in labels if plain.startswith(lbl)), None)
        if matched:
            if current_key and current_lines:
                sections[current_key] = " ".join(current_lines).strip()
            current_key = matched
            rest = re.sub(r"^\s*\([^)]*\)", "", plain[len(matched):])
            rest = rest.lstrip(":- ").strip()
            current_lines = [rest] if rest else []
        elif current_key and plain:
            current_lines.append(plain)

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
async def generate_report(body: ReportRequest, user: AuthUser | None = Depends(ai_user)) -> Response:
    """Generate a free or paid PDF kundali report.

    Paid tier: included with an active premium plan, otherwise it needs a paid report order (create one with
    POST /api/billing/orders, purpose "report", then verify it) whose id is sent as razorpay_order_id. Each paid
    order buys exactly one report and is handed back if the report cannot be produced.
    AUTO_APPROVE_PAYMENTS=true skips the check (development only).
    """
    spent_order = await _authorize_paid_report(body, user)
    try:
        return await _render_report(body)
    except Exception:
        if spent_order and user is not None:
            try:
                async with session_scope() as db:
                    await billing.unconsume_report_payment(db, user.uid, spent_order)
            except Exception as exc:
                logger.error("report_refund_failed", order_id=spent_order, error=str(exc))
        raise


async def _authorize_paid_report(body: ReportRequest, user: AuthUser | None) -> str | None:
    """Raise 402 unless the paid report is allowed. Returns the order id that was spent, if any."""
    settings = get_settings()
    if body.tier != "paid" or settings.auto_approve_payments:
        return None
    if user is None:
        raise HTTPException(status_code=402, detail="Sign in and purchase the report to continue.")
    async with session_scope() as db:
        await accounts.ensure_account(db, user)
        if settings.report_free_for_premium and await accounts.is_premium(db, user.uid):
            return None
        if body.razorpay_order_id and await billing.consume_report_payment(db, user.uid, body.razorpay_order_id):
            return body.razorpay_order_id
    raise HTTPException(status_code=402, detail="Payment required")


async def _render_report(body: ReportRequest) -> Response:
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
            "ascendant": {"sign": _asc_sign(chart_obj.ascendant)},
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
            "yogas": [
                y.get("name", "") if isinstance(y, dict) else str(y)
                for y in chart_obj.yogas
            ],
            "current_dasha": _flat_dasha(chart_obj.current_dasha or {}),
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
