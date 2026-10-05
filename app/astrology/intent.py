"""Question intent classification and routing (deterministic). Maps a concern to topics, modules and specialty."""
from __future__ import annotations

import re

# category -> (prediction topic, suggested modules, astrologer specialty, keywords)
CATEGORIES: dict[str, dict] = {
    "love": {
        "topic": "marriage", "specialty": "Love and relationships",
        "modules": ["compatibility", "love_calculator", "tarot", "horoscope"],
        "keywords": ["love", "relationship", "boyfriend", "girlfriend", "crush", "soulmate", "ex ", "breakup", "break up",
                     "dating", "romance", "propose", "pyaar", "pyar", "prem", "ishq", "mohabbat"],
    },
    "marriage": {
        "topic": "marriage", "specialty": "Marriage and compatibility",
        "modules": ["kundli_milan", "muhurat", "dosha", "predictions"],
        "keywords": ["marriage", "marry", "married", "wedding", "spouse", "husband", "wife", "engagement", "manglik",
                     "kundli milan", "matching", "divorce", "shaadi", "shadi", "vivah", "biwi", "pati", "rishta"],
    },
    "career": {
        "topic": "career", "specialty": "Career and profession",
        "modules": ["predictions", "dasha", "transits", "horoscope"],
        "keywords": ["career", "job", "promotion", "profession", "work", "interview", "resign", "salary", "boss",
                     "office", "unemployed", "naukri", "kaam", "nokri", "transfer"],
    },
    "business": {
        "topic": "finance", "specialty": "Business and finance",
        "modules": ["muhurat", "predictions", "numerology", "vastu"],
        "keywords": ["business", "startup", "start-up", "shop", "partnership", "company", "entrepreneur", "customers",
                     "vyapar", "dhandha", "dukaan", "business partner", "start a business", "open a shop", "new venture"],
    },
    "finance": {
        "topic": "finance", "specialty": "Wealth and finance",
        "modules": ["predictions", "dasha", "remedies", "transits"],
        "keywords": ["money", "wealth", "finance", "financial", "income", "debt", "loan", "investment", "invest", "stock",
                     "savings", "rich", "poverty", "paisa", "paise", "dhan", "karz", "udhar", "lottery"],
    },
    "education": {
        "topic": "education", "specialty": "Education and exams",
        "modules": ["predictions", "horoscope", "remedies"],
        "keywords": ["education", "study", "studies", "exam", "exams", "college", "university", "degree", "admission",
                     "student", "scholarship", "neet", "jee", "upsc", "result", "padhai", "pariksha", "school"],
    },
    "family": {
        "topic": "general", "specialty": "Family and domestic life",
        "modules": ["predictions", "vastu", "remedies"],
        "keywords": ["family", "home", "brother", "sister", "sibling", "in-laws", "in laws", "domestic", "relatives",
                     "ghar", "parivar", "bhai", "behen", "joint family"],
    },
    "parents": {
        "topic": "general", "specialty": "Parents and elders",
        "modules": ["predictions", "remedies", "dosha"],
        "keywords": ["mother", "father", "parents", "mom", "dad", "maa", "papa", "pita", "mata", "ancestors", "pitru"],
    },
    "children": {
        "topic": "children", "specialty": "Children and progeny",
        "modules": ["predictions", "muhurat", "remedies"],
        "keywords": ["child", "children", "baby", "pregnancy", "pregnant", "conceive", "son", "daughter", "progeny",
                     "fertility", "santan", "bachcha", "bachche", "garbh"],
    },
    "health": {
        "topic": "health", "specialty": "Health and wellbeing",
        "modules": ["predictions", "remedies", "dosha"],
        "keywords": ["health", "illness", "disease", "sick", "surgery", "hospital", "pain", "cancer", "diabetes",
                     "depression", "anxiety", "recovery", "sehat", "bimari", "rog", "treatment"],
    },
    "legal": {
        "topic": "general", "specialty": "Legal and disputes",
        "modules": ["predictions", "remedies", "transits"],
        "keywords": ["court", "case", "lawsuit", "legal", "litigation", "dispute", "police", "judge", "bail",
                     "enemy", "enemies", "kanoon", "mukadma", "muqadma"],
    },
    "property": {
        "topic": "property", "specialty": "Property and real estate",
        "modules": ["muhurat", "vastu", "predictions"],
        "keywords": ["property", "house", "flat", "apartment", "land", "plot", "real estate", "buy a home", "construction",
                     "rent", "makaan", "zameen", "ghar kharidna"],
    },
    "travel": {
        "topic": "travel", "specialty": "Travel and foreign settlement",
        "modules": ["muhurat", "predictions", "transits"],
        "keywords": ["travel", "abroad", "foreign", "visa", "immigration", "settle", "overseas", "journey", "trip",
                     "relocate", "videsh", "pardes", "yatra"],
    },
    "spirituality": {
        "topic": "spirituality", "specialty": "Spirituality and dharma",
        "modules": ["remedies", "panchang", "festivals"],
        "keywords": ["spiritual", "meditation", "moksha", "dharma", "karma", "guru", "mantra", "puja", "temple",
                     "god", "yoga", "peace", "purpose", "past life", "bhakti", "sadhana"],
    },
    "numerology": {
        "topic": "general", "specialty": "Numerology", "modules": ["numerology"],
        "keywords": ["numerology", "lucky number", "life path", "mulank", "bhagyank", "name number", "birth number",
                     "meaning of the number", "angel number", "name correction"],
    },
    "tarot": {
        "topic": "general", "specialty": "Tarot", "modules": ["tarot"],
        "keywords": ["tarot", "tarot card", "card reading", "yes or no card", "celtic cross", "pick a card"],
    },
    "vastu": {
        "topic": "property", "specialty": "Vastu Shastra", "modules": ["vastu"],
        "keywords": ["vastu", "north facing", "east facing", "south facing", "west facing", "main entrance", "kitchen direction",
                     "bedroom direction", "pooja room direction", "toilet direction", "vastu dosh"],
    },
    "muhurat": {
        "topic": "general", "specialty": "Muhurat and timing", "modules": ["muhurat"],
        "keywords": ["muhurat", "muhurta", "auspicious date", "auspicious time", "shubh", "good date", "which date", "which day is good",
                     "griha pravesh", "housewarming", "naming ceremony", "mundan", "namkaran", "upanayan"],
    },
    "panchang": {
        "topic": "general", "specialty": "Panchang and festivals", "modules": ["panchang", "festivals"],
        "keywords": ["panchang", "tithi", "nakshatra today", "rahu kaal", "rahu kalam", "choghadiya", "ekadashi", "amavasya",
                     "purnima", "festival", "sunrise", "sunset", "moonrise"],
    },
    "kundli": {
        "topic": "general", "specialty": "Kundli and birth chart", "modules": ["kundli", "dasha", "dosha"],
        "keywords": ["kundli", "kundali", "birth chart", "janam kundli", "janam patri", "lagna", "ascendant", "mahadasha",
                     "antardasha", "dasha", "yoga in my chart", "planets in my chart"],
    },
    "horoscope": {
        "topic": "general", "specialty": "Daily horoscope", "modules": ["horoscope"],
        "keywords": ["horoscope", "rashifal", "rashi", "zodiac", "daily prediction", "today's prediction", "weekly prediction"],
    },
    "remedies": {
        "topic": "general", "specialty": "Remedies and upayas",
        "modules": ["remedies", "dosha", "numerology"],
        "keywords": ["remedy", "remedies", "upay", "upaya", "gemstone", "gem", "stone", "rudraksha", "pooja", "donate",
                     "fasting", "vrat", "shanti", "dosha", "sade sati", "kaal sarp", "kalsarp", "pitru dosh"],
    },
}

_CRISIS = re.compile(
    r"\b(suicid\w*|kill (myself|me)|end (my|this) life|want to die|take my own life|self[- ]?harm|"
    r"no reason to live|don'?t want to live|hurt myself|marne ka mann|jaan de)\b", re.IGNORECASE)

_SAFETY_MESSAGE = (
    "It sounds like you may be going through something very painful. You deserve support from a real person right now. "
    "If you are in immediate danger, please contact your local emergency number. In India you can call Tele-MANAS at 14416 "
    "or the KIRAN helpline at 1800-599-0019 (free, 24x7). Elsewhere, please reach out to a local crisis line or a trusted person."
)

_DISCLAIMERS = {
    "health": "Astrology cannot diagnose or treat medical conditions. Please consult a qualified doctor.",
    "legal": "Astrology is not legal advice. Please consult a qualified lawyer for legal matters.",
    "finance": "Astrology is not financial advice. Please consult a qualified financial adviser before investing.",
    "business": "Astrology is not financial advice. Please consult a qualified adviser before major business decisions.",
}


def classify(text: str) -> dict:
    t = f" {text.lower()} "
    scores: dict[str, float] = {}
    for cat, spec in CATEGORIES.items():
        score = 0.0
        for kw in spec["keywords"]:
            k = kw.lower()
            if " " in k.strip():
                hit = k in t
                weight = 2.0
            else:
                hit = re.search(rf"\b{re.escape(k.strip())}\w*", t) is not None
                weight = 1.0
            if hit:
                score += weight
        if score:
            scores[cat] = score
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    primary = ranked[0][0] if ranked else "general"
    total = sum(scores.values()) or 1.0
    spec = CATEGORIES.get(primary)
    out = {
        "category": primary,
        "confidence": round(scores.get(primary, 0.0) / total, 2) if ranked else 0.0,
        "prediction_topic": spec["topic"] if spec else "general",
        "suggested_modules": spec["modules"] if spec else ["horoscope", "chat"],
        "astrologer_specialty": spec["specialty"] if spec else "General astrology",
        "alternatives": [{"category": c, "score": s} for c, s in ranked[1:4]],
        "disclaimer": _DISCLAIMERS.get(primary),
        "safety": None,
    }
    if _CRISIS.search(text):
        out.update({
            "category": "support", "confidence": 1.0, "prediction_topic": "general",
            "suggested_modules": [], "astrologer_specialty": None, "alternatives": [], "disclaimer": None,
            "safety": {"level": "crisis", "message": _SAFETY_MESSAGE},
        })
    return out


def categories() -> list[dict]:
    return [{"key": k, "specialty": v["specialty"], "topic": v["topic"], "modules": v["modules"]}
            for k, v in CATEGORIES.items()]
