"""Machine-readable catalogue of AstroBro features: what exists, how it works and what is out of scope."""
from __future__ import annotations

# status: live | app_only | planned | out_of_scope
# engine: deterministic (calculated, no LLM) | hybrid (calculation + AI explanation) | ai | human
# suggested_tier: free | free_limited | premium
_F = lambda id_, name, group, desc, engine, tier, status, endpoints=(), notes="": {  # noqa: E731
    "id": id_, "name": name, "group": group, "description": desc, "engine": engine,
    "suggested_tier": tier, "status": status, "endpoints": list(endpoints), "notes": notes,
}

FEATURES: list[dict] = [
    _F("ai_chat", "AI Astrologer chat", "AI Astrologer", "Ask any question in natural language; answers are grounded in your chart and reference texts.",
       "hybrid", "free_limited", "live", ["POST /api/chat/", "POST /api/chat/stream"],
       "Free users get a daily message limit. Throughput depends on the LLM provider's rate limits."),
    _F("ai_predictions", "Topic predictions", "AI Astrologer", "Career, marriage, finance, education, health, children, property, travel and spirituality.",
       "hybrid", "premium", "live", ["POST /api/prediction/"], "Large prompts: needs a paid LLM tier to run reliably at scale."),
    _F("intent_routing", "Concern routing", "AI Astrologer", "Classifies a question (love, career, health, legal...) and suggests the right module or astrologer specialty.",
       "deterministic", "free", "live", ["POST /api/intent/classify"], "Detects crisis language and responds with helpline information."),
    _F("voice_input", "Voice questions", "AI Astrologer", "Speak a question; it is transcribed and can be sent to the chat.",
       "ai", "free_limited", "live", ["POST /api/voice/transcribe"], "Speech-to-text via Whisper; Odia is not supported by the speech model."),
    _F("multilingual", "13 languages", "AI Astrologer", "AI answers in English, Hindi, Marathi, Gujarati, Bengali, Tamil, Telugu, Kannada, Malayalam, Punjabi, Odia, Assamese and Urdu.",
       "ai", "free", "live", ["GET /api/languages"], "Calculated content (horoscope text, panchang labels) is currently English only."),

    _F("kundli", "Kundli / birth chart", "Kundli", "Lagna, planets, houses, nakshatra, aspects, functional nature, Ashtakavarga and Shadbala.",
       "deterministic", "free", "live", ["POST /api/kundli/create"]),
    _F("divisional_charts", "Divisional charts", "Kundli", "D1 to D60 Varga charts.", "deterministic", "free", "live", ["POST /api/kundli/create"]),
    _F("yogas", "Yogas", "Kundli", "50+ classical yogas detected from the chart.", "deterministic", "free", "live", ["POST /api/kundli/create"]),
    _F("dasha", "Dasha timeline", "Kundli", "Vimshottari Maha, Antar and Pratyantar periods with chart-specific meaning, plus Yogini dasha.",
       "deterministic", "free", "live", ["POST /api/dasha/timeline"]),
    _F("doshas", "Dosha analysis", "Kundli", "Manglik, Kaal Sarp, Sade Sati, Pitru, Grahan, Guru Chandala, Angarak, Shrapit, Vish, Gand Mool with cancellations.",
       "deterministic", "free", "live", ["POST /api/dosha/analyze"]),
    _F("transits", "Transits (Gochar)", "Predictions", "Live planetary positions, results from your Moon with Vedha, Sade Sati timeline and upcoming ingresses.",
       "deterministic", "free", "live", ["GET /api/transit/current", "POST /api/transit/natal", "POST /api/transit/sade-sati", "GET /api/transit/events"]),
    _F("horoscope", "Daily, weekly, monthly, yearly horoscope", "Predictions", "By Moon sign, or personalised with Chandra Bala, Tara Bala, Dasha and Sade Sati.",
       "deterministic", "free", "live", ["GET /api/horoscope/{sign}", "GET /api/horoscope/all", "POST /api/horoscope/personal"]),

    _F("kundli_milan", "Kundli Milan", "Compatibility", "36-point Guna Milan, Nadi/Bhakoot/Gana doshas with cancellations, Rajju, Vedha, Manglik, Navamsa and marriage windows.",
       "deterministic", "free_limited", "live", ["POST /api/kundli/match", "POST /api/kundli/match/detailed"]),
    _F("love_calculator", "Love calculator", "Compatibility", "Name-based score and FLAMES, blended with astrological compatibility when birth details are given.",
       "deterministic", "free", "live", ["POST /api/love/calculate"], "Name-based parts are for entertainment."),

    _F("panchang", "Panchang", "Panchang & Calendar", "Tithi, vara, nakshatra, yoga, karana, sunrise/sunset, moonrise/moonset, Rahu Kaal, Choghadiya, Hora.",
       "deterministic", "free", "live", ["GET /api/panchang"]),
    _F("festivals", "Festivals and vratas", "Panchang & Calendar", "Hindu festivals, Ekadashi, Pradosh, Purnima, Amavasya and sankrantis with correct lunar months.",
       "deterministic", "free", "live", ["GET /api/calendar/festivals", "GET /api/calendar/upcoming", "GET /api/calendar/today"],
       "Matches published dates about 9 times in 10; the rest differ by one day due to regional rules."),
    _F("muhurat", "Shubh Muhurat", "Panchang & Calendar", "Auspicious dates and time windows for marriage, griha pravesh, vehicle, property, business, naming, mundan, upanayana, puja and travel.",
       "deterministic", "free_limited", "live", ["GET /api/muhurat/types", "POST /api/muhurat/find"]),

    _F("numerology", "Numerology", "Divination", "Life Path, Destiny, Soul Urge, Personality, personal year, Indian Mulank and Bhagyank, compatibility.",
       "deterministic", "free", "live", ["POST /api/numerology/profile", "POST /api/numerology/compatibility", "GET /api/numerology/daily"]),
    _F("tarot", "Tarot", "Divination", "78-card deck, spreads (single, three-card, yes/no, love, career, decision, Celtic Cross) and card of the day.",
       "deterministic", "free", "live", ["POST /api/tarot/draw", "GET /api/tarot/daily", "GET /api/tarot/cards"], "Optional AI interpretation."),
    _F("vastu", "Vastu", "Vastu", "Room and entrance directions checked against traditional Vastu rules, with remedies.",
       "deterministic", "free", "live", ["POST /api/vastu/analyze", "GET /api/vastu/guidelines"], "Traditional guidance only; not structural advice."),
    _F("remedies", "Remedies", "Remedies", "Gemstones, mantras, donations, fasting and daily practices selected from your chart and doshas.",
       "deterministic", "free_limited", "live", ["POST /api/remedies/personal", "GET /api/remedies/planet/{planet}", "GET /api/remedies/doshas"]),

    _F("reports", "PDF reports", "Reports", "Kundli report as PDF (free), and a detailed AI-personalised premium report.",
       "hybrid", "premium", "live", ["POST /api/report/generate"], "Premium report requires payment (or the launch auto-approve flag)."),
    _F("notifications", "Notifications feed", "Notifications", "Daily horoscope, dasha changes, transit alerts, festivals, vratas and birthdays for local push scheduling.",
       "deterministic", "free", "live", ["POST /api/notifications/feed"], "The backend supplies the feed; the app schedules the alerts."),
    _F("profiles_history", "Profiles, history, saved items", "Profile", "Multiple birth profiles, chat history and saved reports.",
       "deterministic", "free", "app_only", [], "Stored in Firebase by the mobile app."),

    _F("human_consultation", "Chat, call and video with human astrologers", "Marketplace",
       "Per-minute consultations with astrologers the owner has approved, paid minute by minute from a prepaid wallet.",
       "human", "premium", "live",
       ["POST /api/consult/sessions", "GET /api/consult/sessions", "POST /api/consult/sessions/{session_id}/accept",
        "GET /api/consult/sessions/{session_id}/messages", "POST /api/consult/sessions/{session_id}/messages",
        "POST /api/consult/sessions/{session_id}/end", "POST /api/consult/sessions/{session_id}/review"],
       "Chat is near real time (long-polling). Calls and video open a Jitsi room. A chat the astrologer never answers is refunded. "
       "Payouts to astrologers are recorded by the owner and sent by hand (UPI or bank)."),
    _F("astrologer_directory", "Astrologer discovery", "Marketplace", "Filter astrologers by language, price, rating, specialty and who is online.",
       "human", "free", "live", ["GET /api/astrologers", "GET /api/astrologers/{uid}"]),
    _F("astrologer_workspace", "Astrologer dashboard", "Marketplace", "Apply, go online, accept requests, see earnings.",
       "human", "free", "live", ["POST /api/astrologer/apply", "POST /api/astrologer/presence", "GET /api/astrologer/requests",
                                  "GET /api/astrologer/earnings"]),
    _F("wallet", "Wallet", "Marketplace", "Prepaid balance for consultations, topped up through Razorpay.", "deterministic", "free", "live",
       ["GET /api/wallet", "POST /api/billing/orders"]),
    _F("puja_booking", "Puja and pandit booking", "Marketplace", "Book a puja or a pandit visit and pay online; the owner confirms and assigns the pandit.",
       "human", "premium", "live", ["GET /api/services", "POST /api/bookings", "GET /api/bookings"]),
    _F("live_sessions", "Free live astrology sessions", "Marketplace", "Live streamed sessions with astrologers.", "human", "free", "out_of_scope"),

    _F("lal_kitab", "Lal Kitab chart analysis", "Kundli", "Lal Kitab houses, debts (rin) and remedies.", "deterministic", "premium", "planned", [],
       "Needs a licensed or public-domain source for the rule set."),
    _F("kp_system", "KP astrology", "Kundli", "Krishnamurti Paddhati sub-lords and significators.", "deterministic", "premium", "planned"),
]


def catalogue() -> dict:
    groups: dict[str, list[dict]] = {}
    for f in FEATURES:
        groups.setdefault(f["group"], []).append(f)
    counts: dict[str, int] = {}
    for f in FEATURES:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return {"total": len(FEATURES), "by_status": counts, "groups": groups}
