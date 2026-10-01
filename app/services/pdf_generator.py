"""AstroBro PDF report generator (free & paid tiers) using fpdf2."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from fpdf import FPDF

# ── Colour palette ────────────────────────────────────────────────────────────
_ORANGE  = (234, 88, 12)    # AstroBro primary
_GOLD    = (253, 230, 138)  # accent
_DARK    = (30, 27, 22)     # near-black
_GREY    = (120, 113, 108)  # muted
_LIGHT   = (245, 241, 235)  # bg row tint
_WHITE   = (255, 255, 255)

# ── FPDF subclass ─────────────────────────────────────────────────────────────

class _AstroBroPDF(FPDF):
    def __init__(self, name: str, tier: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._name = name
        self._tier = tier
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)

    def header(self):
        # Orange gradient bar
        self.set_fill_color(*_ORANGE)
        self.rect(0, 0, 210, 14, "F")
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_WHITE)
        self.set_xy(6, 3)
        self.cell(0, 8, f"AstroBro  ·  {self._name}  ·  {'PREMIUM REPORT' if self._tier == 'paid' else 'FREE REPORT'}", align="L")
        self.set_text_color(*_DARK)
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_GREY)
        self.cell(0, 4, f"AstroBro AI  ·  Generated {datetime.now().strftime('%d %b %Y')}  ·  Page {self.page_no()}", align="C")

    # ── helpers ───────────────────────────────────────────────────────────────

    def section_title(self, text: str):
        self.ln(4)
        self.set_fill_color(*_ORANGE)
        self.set_text_color(*_WHITE)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, f"  {text}", fill=True, ln=True)
        self.set_text_color(*_DARK)
        self.ln(2)

    def sub_title(self, text: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_ORANGE)
        self.cell(0, 6, text, ln=True)
        self.set_text_color(*_DARK)

    def body_text(self, text: str, indent: float = 0):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        if indent:
            self.set_x(self.get_x() + indent)
        self.multi_cell(0, 5, text)
        self.ln(1)

    def key_value(self, key: str, value: str):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_GREY)
        self.cell(50, 6, key)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        self.cell(0, 6, value, ln=True)

    def table_header(self, cols: list[tuple[str, float]]):
        self.set_fill_color(*_DARK)
        self.set_text_color(*_WHITE)
        self.set_font("Helvetica", "B", 8)
        for label, width in cols:
            self.cell(width, 7, label, border=1, fill=True, align="C")
        self.ln()
        self.set_text_color(*_DARK)

    def table_row(self, values: list[tuple[str, float]], shade: bool):
        if shade:
            self.set_fill_color(*_LIGHT)
        else:
            self.set_fill_color(*_WHITE)
        self.set_font("Helvetica", "", 8)
        for text, width in values:
            self.cell(width, 6, str(text), border=1, fill=True, align="C")
        self.ln()

    def divider(self):
        self.set_draw_color(*_ORANGE)
        self.set_line_width(0.3)
        x = self.get_x()
        y = self.get_y() + 2
        self.line(x, y, 210 - 18, y)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)
        self.ln(4)

    # ── South Indian kundali chart ─────────────────────────────────────────────
    def draw_south_indian_chart(self, planets: dict[str, Any], asc_sign: str):
        """Draw a 4×4 South Indian fixed-sign grid (90×90 mm)."""
        signs = [
            "Pisces",   "Aries",  "Taurus",  "Gemini",
            "Aquarius", None,      None,       "Cancer",
            "Capricorn",None,      None,       "Leo",
            "Sagittarius","Scorpio","Libra",  "Virgo",
        ]

        # map sign → planet abbreviations
        sign_planets: dict[str, list[str]] = {}
        abbr = {
            "Sun":"Su","Moon":"Mo","Mars":"Ma","Mercury":"Me",
            "Jupiter":"Ju","Venus":"Ve","Saturn":"Sa",
            "Rahu":"Ra","Ketu":"Ke","Ascendant":"As",
        }
        for pname, pinfo in planets.items():
            sign = pinfo.get("sign", "")
            short = abbr.get(pname, pname[:2])
            retro = "R" if pinfo.get("retrograde") else ""
            sign_planets.setdefault(sign, []).append(f"{short}{retro}")

        # also place ascendant
        sign_planets.setdefault(asc_sign, []).insert(0, "As")

        cell = 22.5  # mm per cell
        ox = 18.0    # x origin
        oy = self.get_y()

        self.set_font("Helvetica", "", 6)
        self.set_draw_color(*_ORANGE)

        for idx, sign in enumerate(signs):
            row = idx // 4
            col = idx % 4
            x = ox + col * cell
            y = oy + row * cell

            if sign is None:
                # center cells — fill dark
                self.set_fill_color(*_DARK)
                self.rect(x, y, cell, cell, "F")
                continue

            is_asc = (sign == asc_sign)
            self.set_fill_color(*(255, 244, 230) if is_asc else _WHITE)
            self.rect(x, y, cell, cell, "FD")

            # Sign name (top of cell)
            self.set_font("Helvetica", "B", 5)
            self.set_text_color(*_ORANGE)
            self.set_xy(x + 0.5, y + 1)
            self.cell(cell - 1, 3, sign[:3].upper(), align="L")

            # Lagna marker
            if is_asc:
                self.set_font("Helvetica", "B", 5)
                self.set_xy(x + cell - 8, y + 1)
                self.cell(7, 3, "La", align="R")

            # Planet abbreviations
            cell_planets = sign_planets.get(sign, [])
            self.set_font("Helvetica", "", 6)
            self.set_text_color(*_DARK)
            self.set_xy(x + 1, y + 5)
            self.multi_cell(cell - 2, 3.5, " ".join(cell_planets))

        # Draw outer border
        self.set_draw_color(*_ORANGE)
        self.set_line_width(0.6)
        self.rect(ox, oy, cell * 4, cell * 4)
        self.set_line_width(0.2)
        self.set_draw_color(0, 0, 0)
        self.set_text_color(*_DARK)
        self.set_y(oy + cell * 4 + 4)

    # ── Center art (cover) ────────────────────────────────────────────────────
    def cover_art(self):
        self.set_fill_color(*_ORANGE)
        self.rect(0, 0, 210, 297, "F")
        # big Om symbol
        self.set_font("Helvetica", "B", 90)
        self.set_text_color(255, 255, 255, )
        self.set_xy(0, 60)
        self.cell(210, 60, "OM", align="C")
        # tagline
        self.set_font("Helvetica", "", 14)
        self.set_xy(0, 140)
        self.cell(210, 10, "Your Vedic Astrology Report", align="C")


# ── Public API ────────────────────────────────────────────────────────────────

def generate_report_pdf(
    *,
    tier: str,           # "free" | "paid"
    name: str,
    dob: str,            # "YYYY-MM-DD"
    tob: str,            # "HH:MM"
    location: str,
    chart: dict,         # KundliResponse as dict
    ai_sections: dict[str, str] | None = None,  # keyed text for paid
) -> bytes:
    pdf = _AstroBroPDF(name=name, tier=tier)

    # ── Cover page ────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.cover_art()

    # white box overlay
    pdf.set_fill_color(*_WHITE)
    pdf.set_draw_color(*_GOLD)
    pdf.rect(30, 170, 150, 100, "FD")
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*_ORANGE)
    pdf.set_xy(30, 178)
    pdf.cell(150, 12, name, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_DARK)
    pdf.set_xy(30, 192)
    pdf.cell(150, 8, f"Born: {dob}  ·  {tob}", align="C")
    pdf.set_xy(30, 200)
    pdf.cell(150, 8, location, align="C")
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*_ORANGE)
    pdf.set_xy(30, 218)
    tier_label = "PREMIUM KUNDALI REPORT" if tier == "paid" else "KUNDALI REPORT"
    pdf.cell(150, 10, tier_label, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_GREY)
    pdf.set_xy(30, 230)
    pdf.cell(150, 7, f"Generated by AstroBro AI · {datetime.now().strftime('%d %B %Y')}", align="C")

    # ── Page 2: Basic Details + Chart ─────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Birth Details & Avkahada Chakra")

    asc = chart.get("ascendant", {})
    moon_info = chart.get("planets", {}).get("Moon", {})
    moon_nakshatra = chart.get("nakshatra_moon", {})

    pdf.key_value("Name", name)
    pdf.key_value("Date of Birth", dob)
    pdf.key_value("Time of Birth", tob)
    pdf.key_value("Place", location)
    pdf.key_value("Lagna (Ascendant)", asc.get("sign", "-"))
    pdf.key_value("Rasi (Moon Sign)", moon_info.get("sign", "-"))
    pdf.key_value("Nakshatra", moon_nakshatra.get("name", "-"))
    pdf.key_value("Nakshatra Pada", str(moon_nakshatra.get("pada", "-")))
    pdf.key_value("Nakshatra Lord", moon_nakshatra.get("lord", "-"))

    yogas = chart.get("yogas", [])
    if yogas:
        pdf.key_value("Key Yogas", ", ".join(yogas[:5]))

    dasha = chart.get("current_dasha", {})
    if dasha:
        pdf.key_value("Current Mahadasha", dasha.get("mahadasha", "-"))
        pdf.key_value("Current Antardasha", dasha.get("antardasha", "-"))
        pdf.key_value("Dasha End", dasha.get("mahadasha_end", "-"))

    pdf.ln(4)
    pdf.section_title("Kundali Chart (South Indian Style)")
    planets_dict = {
        k: v if isinstance(v, dict) else v.model_dump()
        for k, v in chart.get("planets", {}).items()
    }
    asc_sign = asc.get("sign", "Aries") if isinstance(asc, dict) else str(asc)
    pdf.draw_south_indian_chart(planets_dict, asc_sign)

    # ── Page 3: Planetary Positions ───────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Planetary Positions")
    cols = [("Planet",30),("Sign",28),("House",18),("Degree",22),
            ("Nakshatra",30),("Lord",18),("Status",28)]
    pdf.table_header(cols)
    for i, (pname, pinfo) in enumerate(planets_dict.items()):
        if isinstance(pinfo, dict):
            deg = f"{pinfo.get('degree', 0):.2f}°"
            retro = " ®" if pinfo.get("retrograde") else ""
            combust = " (C)" if pinfo.get("combust") else ""
            status = f"{pinfo.get('dignity', '')}{retro}{combust}".strip()
            row = [
                (pname, 30),
                (pinfo.get("sign", "-"), 28),
                (str(pinfo.get("house", "-")), 18),
                (deg, 22),
                (pinfo.get("nakshatra", "-"), 30),
                (pinfo.get("nakshatra_lord", "-"), 18),
                (status, 28),
            ]
            pdf.table_row(row, shade=(i % 2 == 0))

    # ── Page 4: Life Predictions ──────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Life Predictions")

    ai = ai_sections or {}

    if tier == "free":
        free_areas = ["Career & Profession", "Health & Wellbeing", "Relationships & Marriage"]
        for area in free_areas:
            pdf.sub_title(area)
            text = ai.get(area, _default_prediction(area, asc_sign, moon_info.get("sign", "")))
            pdf.body_text(text)
            pdf.divider()

        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_GREY)
        pdf.multi_cell(0, 5,
            "Upgrade to AstroBro Premium to unlock 12-area life predictions, "
            "Varshaphal, complete Dasha analysis, Lal Kitab, personalized remedies, "
            "and much more.")
        pdf.set_text_color(*_DARK)

    else:
        all_areas = [
            "Career & Profession", "Health & Wellbeing", "Relationships & Marriage",
            "Finance & Wealth", "Education & Knowledge", "Family & Domestic Life",
            "Children & Progeny", "Property & Assets", "Travels & Foreign Connections",
            "Spirituality & Dharma", "Enemies & Legal Matters", "Longevity & Hidden Matters",
        ]
        for area in all_areas:
            pdf.sub_title(area)
            text = ai.get(area, _default_prediction(area, asc_sign, moon_info.get("sign", "")))
            pdf.body_text(text)
            pdf.divider()

    # ── Manglik Dosha ─────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Manglik Dosha Analysis")
    mars = planets_dict.get("Mars", {})
    mars_house = mars.get("house", 0) if isinstance(mars, dict) else 0
    manglik_houses = {1, 4, 7, 8, 12}
    is_manglik = mars_house in manglik_houses
    pdf.sub_title("Result: " + ("Manglik (Mars Dosha Present)" if is_manglik else "Non-Manglik"))
    if is_manglik:
        pdf.body_text(
            f"Mars is placed in the {mars_house}th house of your birth chart. "
            "This placement creates Mangal Dosha, which can affect partnerships and marriage timing. "
            "The intensity varies based on other chart factors. "
            "Remedies include Kumbh Vivah (symbolic marriage before actual marriage), "
            "worship of Lord Hanuman, and wearing a Red Coral gemstone after consulting a Jyotishi."
        )
    else:
        pdf.body_text(
            f"Mars is placed in the {mars_house}th house. "
            "This placement does not create Mangal Dosha. "
            "Your marriage prospects are generally considered free from Mars-related delays."
        )

    # ── Sade Sati ─────────────────────────────────────────────────────────────
    pdf.section_title("Sade Sati & Shani Status")
    pdf.body_text(ai.get("sade_sati",
        "Sade Sati occurs when Saturn transits through the sign before, the sign of, "
        "and the sign after your Moon sign. Check current Saturn position against your "
        f"Moon sign ({moon_info.get('sign', '-')}) to determine active phase. "
        "During Sade Sati, focus on discipline, patience and charitable work."
    ))

    # ── Kalsarpa (paid only) ──────────────────────────────────────────────────
    if tier == "paid":
        pdf.section_title("Kalsarpa Dosh Analysis")
        pdf.body_text(ai.get("kalsarpa",
            "Kalsarpa Dosh is present when all planets are hemmed between Rahu and Ketu. "
            "Analysis of your chart's planetary positions determines whether this Dosh is active "
            "and its specific type (Anant, Kulik, Vasuki etc.). This section provides "
            "specific guidance based on your chart configuration."
        ))

    # ── Vimshottari Dasha Predictions ─────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Vimshottari Dasha Predictions")
    if tier == "free":
        # Only show current period
        pdf.sub_title(f"Current Period: {dasha.get('mahadasha', '-')} Mahadasha")
        pdf.body_text(ai.get("dasha_current",
            f"You are currently in {dasha.get('mahadasha', '-')} Mahadasha, "
            f"running until {dasha.get('mahadasha_end', 'N/A')}. "
            "This period brings themes related to the nature and placement of this planet in your chart. "
            "Upgrade to premium for detailed predictions for all dasha periods."
        ))
    else:
        # All major Mahadasha periods with AI text
        mahadashas = ["Sun","Moon","Mars","Rahu","Jupiter","Saturn",
                      "Mercury","Ketu","Venus"]
        for maha in mahadashas:
            pdf.sub_title(f"{maha} Mahadasha")
            pdf.body_text(ai.get(f"dasha_{maha}",
                _default_dasha_text(maha, planets_dict.get(maha, {}))
            ))
            pdf.divider()

    # ── Transit Today ─────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Key Remedies")
    sun  = planets_dict.get("Sun", {})
    moon_p = planets_dict.get("Moon", {})
    asc_sign_clean = asc_sign.lower()

    remedies = _get_remedies(asc_sign_clean, dasha.get("mahadasha", ""))
    for i, (title, remedy) in enumerate(remedies.items(), 1):
        pdf.sub_title(f"{i}. {title}")
        pdf.body_text(remedy)

    # ── Paid extras ───────────────────────────────────────────────────────────
    if tier == "paid":
        pdf.add_page()
        pdf.section_title("Varshaphal — Annual Predictions")
        pdf.body_text(ai.get("varshaphal",
            "Varshaphal (Solar Return) chart is cast for the moment the Sun returns to "
            "its natal position in a given year. This annual chart reveals themes, opportunities, "
            "and challenges for the current year of your life. The Muntha, Year Lord, "
            "and active sub-dashas within the Varshaphal are analysed to give month-by-month guidance."
        ))

        pdf.add_page()
        pdf.section_title("Lal Kitab Analysis")
        pdf.body_text(ai.get("lal_kitab",
            "Lal Kitab is a unique system of Vedic astrology from the Punjab tradition. "
            "It uses the Janm Kundali (natal chart) but interprets planetary placements "
            "differently, with specific upayas (remedies) that are practical and accessible. "
            "The following section details each planet's placement in your chart according "
            "to Lal Kitab principles, with associated remedies for each planet."
        ))

        for pname in ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn","Rahu","Ketu"]:
            pinfo = planets_dict.get(pname, {})
            house = pinfo.get("house", "-") if isinstance(pinfo, dict) else "-"
            pdf.sub_title(f"{pname} in {house}th House (Lal Kitab)")
            pdf.body_text(ai.get(f"lal_kitab_{pname}",
                f"{pname} placed in house {house} in your Lal Kitab chart indicates specific "
                f"results and requires particular remedies based on planetary friendships and "
                f"the nature of the house lord."
            ))
            pdf.divider()

        pdf.add_page()
        pdf.section_title("Lucky Profile")
        lucky = ai.get("lucky_profile", "")
        if not lucky:
            lucky = _lucky_profile(asc_sign)
        pdf.body_text(lucky)

        pdf.add_page()
        pdf.section_title("Year-Ahead Monthly Forecast")
        pdf.body_text(ai.get("monthly_forecast",
            "Your 12-month forecast is generated based on the combined analysis of "
            "Vimshottari Dasha, Varshaphal sub-dashas, and major planetary transits. "
            "Each month is assessed for career, finance, health, and relationship themes."
        ))

    # ── Footer page ───────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_ORANGE)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(0, 100)
    pdf.cell(210, 12, "Thank You", align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(0, 116)
    pdf.multi_cell(210, 7,
        "This report was generated by AstroBro AI.\n"
        "For live chat with your AI Jyotish, open the AstroBro app.\n\n"
        "May the stars guide your path.",
        align="C")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


# ── Default text fallbacks ────────────────────────────────────────────────────

def _default_prediction(area: str, lagna: str, moon_sign: str) -> str:
    return (
        f"Based on your {lagna} ascendant and {moon_sign} Moon sign, "
        f"this section provides insights into your {area.lower()}. "
        "The planetary positions and dasha periods create a unique pattern "
        "of opportunities and challenges in this life area. "
        "For a deeply personalised AI-generated analysis, please consult "
        "the AstroBro AI chat."
    )


def _default_dasha_text(planet: str, pinfo: dict) -> str:
    house = pinfo.get("house", "?") if isinstance(pinfo, dict) else "?"
    sign  = pinfo.get("sign", "?") if isinstance(pinfo, dict) else "?"
    return (
        f"{planet} Mahadasha brings themes related to {planet}'s significations. "
        f"In your chart, {planet} is placed in {sign} in the {house}th house. "
        "Results will be coloured by the nature of this planet, its dignity, "
        "aspects received, and the ongoing Antardasha sub-periods."
    )


def _get_remedies(lagna: str, mahadasha: str) -> dict[str, str]:
    return {
        "Gemstone Therapy": (
            f"For your {lagna.capitalize()} ascendant and current {mahadasha} Mahadasha, "
            "consult a qualified Jyotishi before wearing any gemstone. General recommendations "
            "are based on the ascendant lord's gemstone and the current dasha lord's gemstone."
        ),
        "Mantra Practice": (
            f"Chanting the Beej Mantra of your ascendant lord and the current Mahadasha "
            f"planet ({mahadasha}) 108 times daily is highly recommended. "
            "Morning practice facing East after a bath gives best results."
        ),
        "Charity & Service": (
            "Charitable acts aligned with the struggling planets in your chart bring relief. "
            "Donate items associated with malefic planets on their respective weekdays. "
            "Service to the underprivileged strengthens benefic planets."
        ),
        "Fasting": (
            "Keeping a fast on the day ruled by your Mahadasha planet strengthens its positive "
            "effects and weakens its malefic tendencies."
        ),
        "Worship": (
            "Regular temple visits and puja of your Ishta Devata (preferred deity) based on "
            "your 5th house lord and its placement will bring blessings and inner clarity."
        ),
    }


def _lucky_profile(lagna: str) -> str:
    profiles: dict[str, dict] = {
        "aries":      {"color":"Red, Coral",      "day":"Tuesday",  "number":"9",     "gem":"Red Coral", "deity":"Lord Hanuman"},
        "taurus":     {"color":"White, Pink",      "day":"Friday",   "number":"6",     "gem":"Diamond/White Sapphire", "deity":"Goddess Lakshmi"},
        "gemini":     {"color":"Green, Yellow",    "day":"Wednesday","number":"5",     "gem":"Emerald",   "deity":"Lord Vishnu"},
        "cancer":     {"color":"White, Silver",    "day":"Monday",   "number":"2",     "gem":"Pearl",     "deity":"Lord Shiva"},
        "leo":        {"color":"Gold, Orange",     "day":"Sunday",   "number":"1",     "gem":"Ruby",      "deity":"Lord Surya"},
        "virgo":      {"color":"Green, Brown",     "day":"Wednesday","number":"5",     "gem":"Emerald",   "deity":"Lord Vishnu"},
        "libra":      {"color":"White, Blue",      "day":"Friday",   "number":"6",     "gem":"Diamond",   "deity":"Goddess Saraswati"},
        "scorpio":    {"color":"Red, Dark Blue",   "day":"Tuesday",  "number":"9",     "gem":"Red Coral", "deity":"Lord Karthikeya"},
        "sagittarius":{"color":"Yellow, Purple",   "day":"Thursday", "number":"3",     "gem":"Yellow Sapphire","deity":"Lord Brahma"},
        "capricorn":  {"color":"Black, Blue",      "day":"Saturday", "number":"8",     "gem":"Blue Sapphire","deity":"Lord Shani"},
        "aquarius":   {"color":"Blue, Violet",     "day":"Saturday", "number":"8",     "gem":"Blue Sapphire","deity":"Lord Shani"},
        "pisces":     {"color":"Yellow, Sea Green","day":"Thursday", "number":"3",     "gem":"Yellow Sapphire","deity":"Lord Vishnu"},
    }
    p = profiles.get(lagna.lower(), profiles["aries"])
    return (
        f"Lucky Colors: {p['color']}\n"
        f"Lucky Day: {p['day']}\n"
        f"Lucky Number: {p['number']}\n"
        f"Recommended Gemstone: {p['gem']}\n"
        f"Favourable Deity for Worship: {p['deity']}\n"
        f"Lucky Direction: East (general — varies by ascendant)\n"
        f"Lucky Metal: Based on ascendant lord's nature"
    )
