"""Astrological constants — single source of truth."""
from __future__ import annotations

SIGNS: list[str] = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

SIGN_LORDS: list[str] = [
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
]

NAKSHATRAS: list[str] = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha",
    "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha",
    "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
]

# 9 lords repeat 3x = 27
_NAK_LORD_BASE: list[str] = [
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu",
    "Jupiter", "Saturn", "Mercury",
]
NAKSHATRA_LORDS: list[str] = _NAK_LORD_BASE * 3

DASHA_SEQUENCE: list[str] = [
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
]
DASHA_YEARS: dict[str, int] = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10,
    "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}

# sign_index → which sign (0=Aries … 11=Pisces)
EXALTATION: dict[str, dict[str, int]] = {
    "Sun": {"sign": 0, "degree": 10},
    "Moon": {"sign": 1, "degree": 3},
    "Mars": {"sign": 9, "degree": 28},
    "Mercury": {"sign": 5, "degree": 15},
    "Jupiter": {"sign": 3, "degree": 5},
    "Venus": {"sign": 11, "degree": 27},
    "Saturn": {"sign": 6, "degree": 20},
}

DEBILITATION: dict[str, dict[str, int]] = {
    "Sun": {"sign": 6, "degree": 10},
    "Moon": {"sign": 7, "degree": 3},
    "Mars": {"sign": 3, "degree": 28},
    "Mercury": {"sign": 11, "degree": 15},
    "Jupiter": {"sign": 9, "degree": 5},
    "Venus": {"sign": 5, "degree": 27},
    "Saturn": {"sign": 0, "degree": 20},
}

MOOLATRIKONA: dict[str, dict[str, float]] = {
    "Sun":     {"sign": 4,  "start": 0,  "end": 20},
    "Moon":    {"sign": 1,  "start": 3,  "end": 30},
    "Mars":    {"sign": 0,  "start": 0,  "end": 12},
    "Mercury": {"sign": 5,  "start": 16, "end": 20},
    "Jupiter": {"sign": 8,  "start": 0,  "end": 10},
    "Venus":   {"sign": 6,  "start": 0,  "end": 15},
    "Saturn":  {"sign": 10, "start": 0,  "end": 20},
}

# degrees of combustion orb per planet
COMBUSTION_ORBS: dict[str, float] = {
    "Moon": 12, "Mars": 17, "Mercury": 14,
    "Jupiter": 11, "Venus": 10, "Saturn": 15,
}

HOUSE_SIGNIFICATIONS: dict[int, str] = {
    1:  "self, body, personality, vitality",
    2:  "wealth, family, speech, values",
    3:  "siblings, courage, communication, short journeys",
    4:  "mother, home, property, education, happiness",
    5:  "children, intelligence, creativity, romance",
    6:  "enemies, disease, service, competition",
    7:  "spouse, partnership, marriage, business",
    8:  "longevity, transformation, occult, inheritance",
    9:  "father, dharma, luck, higher education, pilgrimage",
    10: "career, profession, status, authority",
    11: "gains, income, friends, aspirations",
    12: "loss, liberation, foreign lands, spirituality",
}

# Natural friendships (simplified)
NATURAL_FRIENDS: dict[str, list[str]] = {
    "Sun":     ["Moon", "Mars", "Jupiter"],
    "Moon":    ["Sun", "Mercury"],
    "Mars":    ["Sun", "Moon", "Jupiter"],
    "Mercury": ["Sun", "Venus"],
    "Jupiter": ["Sun", "Moon", "Mars"],
    "Venus":   ["Mercury", "Saturn"],
    "Saturn":  ["Mercury", "Venus"],
    "Rahu":    [],
    "Ketu":    [],
}

NATURAL_ENEMIES: dict[str, list[str]] = {
    "Sun":     ["Venus", "Saturn"],
    "Moon":    [],
    "Mars":    ["Mercury"],
    "Mercury": ["Moon"],
    "Jupiter": ["Mercury", "Venus"],
    "Venus":   ["Sun", "Moon"],
    "Saturn":  ["Sun", "Moon", "Mars"],
    "Rahu":    [],
    "Ketu":    [],
}
