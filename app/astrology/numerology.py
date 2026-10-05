"""Numerology: Pythagorean profile, Chaldean name number, Indian Mulank/Bhagyank, compatibility. Deterministic."""
from __future__ import annotations

from datetime import date

_PYTHAGOREAN = {c: n for n, letters in {
    1: "AJS", 2: "BKT", 3: "CLU", 4: "DMV", 5: "ENW", 6: "FOX", 7: "GPY", 8: "HQZ", 9: "IR",
}.items() for c in letters}
_CHALDEAN = {c: n for n, letters in {
    1: "AIJQY", 2: "BKR", 3: "CGLS", 4: "DMT", 5: "EHNX", 6: "UVW", 7: "OZ", 8: "FP",
}.items() for c in letters}
_VOWELS = set("AEIOU")
MASTERS = {11, 22, 33}

# Indian numerology: number -> ruling planet
_RULER = {1: "Sun", 2: "Moon", 3: "Jupiter", 4: "Rahu", 5: "Mercury", 6: "Venus", 7: "Ketu", 8: "Saturn", 9: "Mars"}
_RULER_DAY = {"Sun": "Sunday", "Moon": "Monday", "Mars": "Tuesday", "Mercury": "Wednesday",
              "Jupiter": "Thursday", "Venus": "Friday", "Saturn": "Saturday", "Rahu": "Saturday", "Ketu": "Tuesday"}
_RULER_COLOUR = {"Sun": "Gold, saffron", "Moon": "White, cream", "Mars": "Red, maroon", "Mercury": "Green",
                 "Jupiter": "Yellow", "Venus": "White, pink", "Saturn": "Dark blue, black",
                 "Rahu": "Grey, smoky blue", "Ketu": "Brown, multi-colour"}
_RULER_GEM = {"Sun": "Ruby", "Moon": "Pearl", "Mars": "Red Coral", "Mercury": "Emerald", "Jupiter": "Yellow Sapphire",
              "Venus": "Diamond or White Sapphire", "Saturn": "Blue Sapphire (with expert advice)",
              "Rahu": "Hessonite (with expert advice)", "Ketu": "Cat's Eye (with expert advice)"}
_FRIENDS = {1: [2, 3, 9], 2: [1, 5], 3: [1, 2, 9], 4: [5, 6, 8], 5: [1, 4, 6], 6: [4, 5, 8],
            7: [1, 6, 9], 8: [4, 5, 6], 9: [1, 2, 3]}
_ENEMIES = {1: [6, 8], 2: [4, 8], 3: [5, 6], 4: [1, 2, 9], 5: [3], 6: [1, 3], 7: [2, 8], 8: [1, 2, 9], 9: [4, 5, 8]}

NUMBER_PROFILES: dict[int, dict[str, str]] = {
    1: {"title": "The Leader", "strengths": "independent, original and determined",
        "challenges": "stubbornness and a tendency to dominate", "career": "leadership, entrepreneurship, innovation",
        "love": "needs a partner who respects independence", "advice": "Take the initiative, and make room for other voices."},
    2: {"title": "The Diplomat", "strengths": "cooperative, intuitive and gentle",
        "challenges": "oversensitivity and indecision", "career": "counselling, partnerships, the arts, mediation",
        "love": "devoted and caring; thrives on harmony", "advice": "Trust your intuition and speak up for your needs."},
    3: {"title": "The Communicator", "strengths": "creative, expressive and optimistic",
        "challenges": "scattered energy and avoidance of depth", "career": "writing, teaching, media, performance",
        "love": "playful and affectionate; needs lively company", "advice": "Channel your creativity into finished work."},
    4: {"title": "The Builder", "strengths": "practical, disciplined and dependable",
        "challenges": "rigidity and overwork", "career": "engineering, management, finance, craftsmanship",
        "love": "loyal and steady; shows love through action", "advice": "Build step by step, and allow some flexibility."},
    5: {"title": "The Adventurer", "strengths": "adaptable, curious and freedom-loving",
        "challenges": "restlessness and impulsiveness", "career": "travel, sales, media, anything with variety",
        "love": "needs excitement and freedom in a relationship", "advice": "Embrace change, but commit to what matters."},
    6: {"title": "The Nurturer", "strengths": "responsible, caring and harmonious",
        "challenges": "over-responsibility and perfectionism", "career": "healthcare, teaching, design, community work",
        "love": "devoted to home and family", "advice": "Care for others without losing yourself."},
    7: {"title": "The Seeker", "strengths": "analytical, spiritual and perceptive",
        "challenges": "withdrawal and over-analysis", "career": "research, science, philosophy, technology",
        "love": "needs depth, privacy and trust", "advice": "Make time for solitude and for connection."},
    8: {"title": "The Achiever", "strengths": "ambitious, organised and resilient",
        "challenges": "workaholism and a focus on status", "career": "business, finance, law, executive roles",
        "love": "committed; needs a partner who shares ambition", "advice": "Use power with fairness and keep balance."},
    9: {"title": "The Humanitarian", "strengths": "compassionate, generous and idealistic",
        "challenges": "difficulty letting go and martyrdom", "career": "healing, charity, the arts, teaching",
        "love": "romantic and giving; needs emotional depth", "advice": "Give freely, and release what has ended."},
    11: {"title": "The Illuminator (master number)", "strengths": "intuitive, inspiring and idealistic",
         "challenges": "nervous tension and high self-expectation", "career": "inspirational teaching, the arts, healing, counselling",
         "love": "deeply sensitive; needs an understanding partner", "advice": "Ground your vision in daily practice."},
    22: {"title": "The Master Builder (master number)", "strengths": "visionary and capable of large-scale achievement",
         "challenges": "pressure and fear of falling short", "career": "large projects, architecture, organisations",
         "love": "steady and protective", "advice": "Turn big dreams into patient plans."},
    33: {"title": "The Master Teacher (master number)", "strengths": "selfless, nurturing and uplifting",
         "challenges": "carrying others' burdens", "career": "teaching, healing, service to communities",
         "love": "devoted and compassionate", "advice": "Serve with healthy boundaries."},
}

_FRAMES = {
    "life_path": "Your Life Path shows your core purpose and the lessons of this life.",
    "destiny": "Your Destiny (Expression) number shows your natural talents and what you are here to achieve.",
    "soul_urge": "Your Soul Urge reveals what your heart truly wants.",
    "personality": "Your Personality number describes the impression you give others.",
    "birthday": "Your Birthday number is a special talent you carry.",
}
_PERSONAL_YEAR = {
    1: "A year of new beginnings: plant seeds and take initiative.",
    2: "A year of patience and partnership: cooperate and let things develop.",
    3: "A year of creativity and social growth: express yourself.",
    4: "A year of work and foundations: organise, build and be disciplined.",
    5: "A year of change and freedom: expect movement, travel and new options.",
    6: "A year of home, family and responsibility: nurture relationships.",
    7: "A year of reflection and study: slow down and look inward.",
    8: "A year of career and money: ambition and rewards are in focus.",
    9: "A year of completion: release what has run its course and prepare for a new cycle.",
}


# ── Reduction helpers ─────────────────────────────────────────────────────────

def reduce_number(n: int, keep_master: bool = True) -> int:
    while n > 9 and not (keep_master and n in MASTERS):
        n = sum(int(d) for d in str(n))
    return n


def _digits_sum(n: int) -> int:
    return sum(int(d) for d in str(abs(n)))


def _clean(name: str) -> str:
    return "".join(c for c in name.upper() if c.isalpha() and c.isascii())


def _word_letters(name: str) -> list[tuple[str, bool]]:
    """(letter, is_vowel) with Y counted as a vowel only when its word has no other vowel."""
    out = []
    for word in name.upper().split():
        w = "".join(c for c in word if c.isalpha() and c.isascii())
        has_vowel = any(c in _VOWELS for c in w)
        for c in w:
            out.append((c, c in _VOWELS or (c == "Y" and not has_vowel)))
    return out


def _name_total(letters: list[tuple[str, bool]], table: dict[str, int], pick) -> int:
    return sum(table[c] for c, v in letters if pick(v) and c in table)


# ── Public API ────────────────────────────────────────────────────────────────

def life_path(dob: date) -> int:
    return reduce_number(reduce_number(dob.month) + reduce_number(dob.day) + reduce_number(_digits_sum(dob.year)))


def mulank(dob: date) -> int:
    return reduce_number(dob.day, keep_master=False)


def bhagyank(dob: date) -> int:
    return reduce_number(_digits_sum(int(dob.strftime("%d%m%Y"))), keep_master=False)


def _entry(kind: str, n: int) -> dict:
    if n not in NUMBER_PROFILES:
        return {"number": None, "title": None, "master_number": False,
                "meaning": "Not available: this name has no letters of the kind this number counts.",
                "strengths": None, "challenges": None, "career": None, "love": None, "advice": None}
    p = NUMBER_PROFILES[n]
    return {
        "number": n, "title": p["title"], "master_number": n in MASTERS,
        "meaning": f"{_FRAMES[kind]} As a {n} you are {p['strengths']}.",
        "strengths": p["strengths"], "challenges": p["challenges"],
        "career": p["career"], "love": p["love"], "advice": p["advice"],
    }


def profile(name: str, dob: date, today: date | None = None) -> dict:
    today = today or date.today()
    letters = _word_letters(name)
    if not letters:
        raise ValueError("Please enter the name using English letters (A-Z).")
    destiny = reduce_number(_name_total(letters, _PYTHAGOREAN, lambda v: True))
    soul = reduce_number(_name_total(letters, _PYTHAGOREAN, lambda v: v))
    personality = reduce_number(_name_total(letters, _PYTHAGOREAN, lambda v: not v))
    lp = life_path(dob)
    birthday = reduce_number(dob.day)
    chaldean = reduce_number(sum(_CHALDEAN.get(c, 0) for c, _ in letters), keep_master=False)

    py = reduce_number(reduce_number(dob.month) + reduce_number(dob.day) + reduce_number(_digits_sum(today.year)), keep_master=False)
    pm = reduce_number(py + today.month, keep_master=False)
    pd = reduce_number(pm + today.day, keep_master=False)

    mk, bk = mulank(dob), bhagyank(dob)
    ruler = _RULER[mk]
    lucky = sorted({mk, bk, lp if lp <= 9 else reduce_number(lp, False), destiny if destiny <= 9 else reduce_number(destiny, False)})

    return {
        "name": name, "date_of_birth": dob.isoformat(),
        "life_path": _entry("life_path", lp),
        "destiny": _entry("destiny", destiny),
        "soul_urge": _entry("soul_urge", soul),
        "personality": _entry("personality", personality),
        "birthday": _entry("birthday", birthday),
        "maturity": {"number": reduce_number(lp + destiny), "note": "Who you grow into in the second half of life."},
        "attitude": {"number": reduce_number(dob.day + dob.month, keep_master=False),
                     "note": "How others first perceive your approach to life."},
        "personal_cycle": {
            "year": {"number": py, "meaning": _PERSONAL_YEAR[py], "calendar_year": today.year},
            "month": {"number": pm, "calendar_month": today.month},
            "day": {"number": pd, "date": today.isoformat()},
        },
        "chaldean_name_number": {"number": chaldean, "ruling_planet": _RULER[chaldean] if chaldean in _RULER else None},
        "indian": {
            "mulank": mk, "bhagyank": bk, "ruling_planet": ruler,
            "bhagyank_planet": _RULER[bk],
            "lucky_numbers": lucky,
            "lucky_day": _RULER_DAY[ruler], "lucky_colours": _RULER_COLOUR[ruler],
            "gemstone": _RULER_GEM[ruler],
            "friendly_numbers": _FRIENDS[mk], "challenging_numbers": _ENEMIES[mk],
        },
        "note": "Numerology is a traditional system for reflection and entertainment, not a prediction of fact.",
    }


_FAMILIES = [{1, 5, 7}, {2, 4, 8}, {3, 6, 9}]
_COMPLEMENTARY = {frozenset(p) for p in [(1, 2), (1, 3), (2, 6), (3, 5), (4, 6), (6, 9), (7, 9), (5, 9), (3, 9), (2, 7), (4, 8), (5, 7)]}


def _number_compat(a: int, b: int) -> int:
    a, b = reduce_number(a, False), reduce_number(b, False)
    if a == b:
        return 82
    if any(a in f and b in f for f in _FAMILIES):
        return 88
    if frozenset((a, b)) in _COMPLEMENTARY:
        return 74
    if b in _ENEMIES.get(a, []) or a in _ENEMIES.get(b, []):
        return 38
    return 58


def compatibility(name_a: str, dob_a: date, name_b: str, dob_b: date) -> dict:
    a, b = profile(name_a, dob_a), profile(name_b, dob_b)
    pairs = {
        "life_path": (a["life_path"]["number"], b["life_path"]["number"], 0.35),
        "destiny": (a["destiny"]["number"], b["destiny"]["number"], 0.2),
        "soul_urge": (a["soul_urge"]["number"], b["soul_urge"]["number"], 0.2),
        "mulank": (a["indian"]["mulank"], b["indian"]["mulank"], 0.25),
    }
    parts = {k: _number_compat(x, y) for k, (x, y, _w) in pairs.items() if x and y}
    weight = sum(pairs[k][2] for k in parts)
    score = round(sum(parts[k] * pairs[k][2] for k in parts) / weight)
    label = "excellent" if score >= 80 else "good" if score >= 65 else "moderate" if score >= 50 else "needs effort"
    return {
        "people": [{"name": name_a, "life_path": a["life_path"]["number"], "mulank": a["indian"]["mulank"]},
                   {"name": name_b, "life_path": b["life_path"]["number"], "mulank": b["indian"]["mulank"]}],
        "score": score, "label": label, "breakdown": parts,
        "summary": f"Life Paths {a['life_path']['number']} and {b['life_path']['number']} give a {label} numerological match.",
        "note": "For reflection and entertainment.",
    }


def daily_number(dob: date, today: date) -> dict:
    n = reduce_number(reduce_number(dob.month + dob.day, False) + reduce_number(_digits_sum(int(today.strftime("%d%m%Y"))), False), False)
    return {"date": today.isoformat(), "number": n, "ruling_planet": _RULER[n],
            "theme": _PERSONAL_YEAR[n].replace("A year", "A day").replace("this year", "today"),
            "lucky_colour": _RULER_COLOUR[_RULER[n]]}
