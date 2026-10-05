"""Traditional Jyotish remedies (upayas): planet and dosha based, with chart-aware selection.

All items are traditional practices offered as guidance, not guarantees. Gemstones in particular
should be worn only after a trial and advice from a qualified astrologer.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.astrology import dasha as D
from app.astrology import strength as S

DISCLAIMER = (
    "These are traditional practices shared for guidance and personal faith. They are not a substitute "
    "for medical, legal or financial advice, and results cannot be guaranteed. Consult a qualified "
    "astrologer before wearing any gemstone."
)

PLANET_REMEDIES: dict[str, dict] = {
    "Sun": {
        "gemstone": {"name": "Ruby (Manik)", "alternative": "Red garnet or red spinel", "metal": "Gold or copper",
                     "finger": "Ring finger", "day": "Sunday, in the morning"},
        "mantra": {"beej": "Om Hram Hreem Hraum Sah Suryaya Namah", "japa": "108 times daily, facing east at sunrise",
                   "other": "Aditya Hridayam stotra"},
        "deity": "Surya (Sun God)", "fast_day": "Sunday",
        "donate": ["wheat", "jaggery", "copper items", "red cloth"], "donate_day": "Sunday",
        "colour": "Saffron or red", "rudraksha": "1 or 12 Mukhi",
        "daily_practice": "Offer water to the rising Sun and begin the day with gratitude.",
        "folk_upaya": "Rise early, avoid arrogance, and serve your father or father figures.",
    },
    "Moon": {
        "gemstone": {"name": "Pearl (Moti)", "alternative": "Moonstone", "metal": "Silver",
                     "finger": "Little finger", "day": "Monday evening"},
        "mantra": {"beej": "Om Shram Shreem Shraum Sah Chandraya Namah", "japa": "108 times daily, in the evening",
                   "other": "Chandra Kavacham or Shiva mantras"},
        "deity": "Shiva and Parvati", "fast_day": "Monday",
        "donate": ["rice", "milk", "white cloth", "silver items"], "donate_day": "Monday",
        "colour": "White or cream", "rudraksha": "2 Mukhi",
        "daily_practice": "Spend a few quiet minutes each evening and drink water from a silver or clean glass vessel.",
        "folk_upaya": "Respect and care for your mother; keep emotions balanced and routines regular.",
    },
    "Mars": {
        "gemstone": {"name": "Red Coral (Moonga)", "alternative": "Carnelian or red jasper", "metal": "Copper or gold",
                    "finger": "Ring finger", "day": "Tuesday morning"},
        "mantra": {"beej": "Om Kram Kreem Kraum Sah Bhaumaya Namah", "japa": "108 times daily, on Tuesdays especially",
                   "other": "Hanuman Chalisa"},
        "deity": "Hanuman and Kartikeya", "fast_day": "Tuesday",
        "donate": ["red lentils (masoor)", "jaggery", "red cloth", "copper items"], "donate_day": "Tuesday",
        "colour": "Red", "rudraksha": "3 Mukhi",
        "daily_practice": "Channel energy into exercise and avoid reacting in anger.",
        "folk_upaya": "Offer sweets at a Hanuman temple on Tuesdays and keep good relations with brothers.",
    },
    "Mercury": {
        "gemstone": {"name": "Emerald (Panna)", "alternative": "Green tourmaline or peridot", "metal": "Gold or bronze",
                     "finger": "Little finger", "day": "Wednesday morning"},
        "mantra": {"beej": "Om Bram Breem Braum Sah Budhaya Namah", "japa": "108 times daily, on Wednesdays especially",
                   "other": "Vishnu Sahasranama"},
        "deity": "Vishnu and Ganesha", "fast_day": "Wednesday",
        "donate": ["green moong", "green cloth", "books or stationery"], "donate_day": "Wednesday",
        "colour": "Green", "rudraksha": "4 Mukhi",
        "daily_practice": "Keep your speech truthful and spend time reading or learning.",
        "folk_upaya": "Feed green fodder to a cow on Wednesdays and help students.",
    },
    "Jupiter": {
        "gemstone": {"name": "Yellow Sapphire (Pukhraj)", "alternative": "Yellow topaz or citrine", "metal": "Gold",
                     "finger": "Index finger", "day": "Thursday morning"},
        "mantra": {"beej": "Om Gram Greem Graum Sah Gurave Namah", "japa": "108 times daily, on Thursdays especially",
                   "other": "Guru Stotra or Vishnu Sahasranama"},
        "deity": "Brihaspati and Vishnu", "fast_day": "Thursday",
        "donate": ["chana dal", "turmeric", "yellow cloth", "books"], "donate_day": "Thursday",
        "colour": "Yellow", "rudraksha": "5 Mukhi",
        "daily_practice": "Seek the guidance of teachers and elders and share knowledge generously.",
        "folk_upaya": "Respect your guru, apply a turmeric or saffron tilak and feed cows with chana on Thursdays.",
    },
    "Venus": {
        "gemstone": {"name": "Diamond (Heera)", "alternative": "White sapphire, zircon or opal", "metal": "Silver or platinum",
                     "finger": "Middle or ring finger", "day": "Friday morning"},
        "mantra": {"beej": "Om Dram Dreem Draum Sah Shukraya Namah", "japa": "108 times daily, on Fridays especially",
                   "other": "Shri Sukta or Lakshmi mantras"},
        "deity": "Lakshmi and Durga", "fast_day": "Friday",
        "donate": ["rice", "sugar", "white or pink cloth", "perfume"], "donate_day": "Friday",
        "colour": "White or pink", "rudraksha": "6 Mukhi",
        "daily_practice": "Keep your home clean and fragrant and nurture your relationships.",
        "folk_upaya": "Respect women, donate white sweets on Fridays and avoid excess indulgence.",
    },
    "Saturn": {
        "gemstone": {"name": "Blue Sapphire (Neelam)", "alternative": "Amethyst or lapis lazuli", "metal": "Iron or silver",
                     "finger": "Middle finger", "day": "Saturday evening",
                     "caution": "Blue Sapphire acts fast and strongly; wear only after a trial period and expert advice."},
        "mantra": {"beej": "Om Pram Preem Praum Sah Shanaye Namah", "japa": "108 times daily, on Saturdays especially",
                   "other": "Hanuman Chalisa or Shani Stotra"},
        "deity": "Shani Dev and Hanuman", "fast_day": "Saturday",
        "donate": ["black sesame", "mustard oil", "iron items", "black cloth or blankets"], "donate_day": "Saturday",
        "colour": "Dark blue or black", "rudraksha": "7 or 14 Mukhi",
        "daily_practice": "Be disciplined and punctual, and treat workers and elders with respect.",
        "folk_upaya": "Light a mustard-oil lamp under a peepal tree on Saturdays and serve the elderly.",
    },
    "Rahu": {
        "gemstone": {"name": "Hessonite (Gomed)", "alternative": "Orange zircon", "metal": "Silver or ashtadhatu",
                     "finger": "Middle finger", "day": "Saturday evening",
                     "caution": "Rahu's stone can amplify confusion if the planet is poorly placed; seek expert advice."},
        "mantra": {"beej": "Om Bhram Bhreem Bhraum Sah Rahave Namah", "japa": "108 times daily, in the evening",
                   "other": "Durga Chalisa"},
        "deity": "Durga and Bhairava", "fast_day": "Saturday",
        "donate": ["black or blue cloth", "mustard", "blankets"], "donate_day": "Saturday",
        "colour": "Smoky grey or dark blue", "rudraksha": "8 Mukhi",
        "daily_practice": "Stay away from intoxicants and shortcuts, and keep your surroundings clean.",
        "folk_upaya": "Feed birds, donate to those in need and avoid dishonest dealings.",
    },
    "Ketu": {
        "gemstone": {"name": "Cat's Eye (Lehsunia)", "alternative": "Tiger's eye", "metal": "Silver or ashtadhatu",
                     "finger": "Middle finger", "day": "Tuesday or Thursday evening",
                     "caution": "Wear only after expert advice; Ketu's stone intensifies detachment."},
        "mantra": {"beej": "Om Shram Shreem Shraum Sah Ketave Namah", "japa": "108 times daily, at dusk",
                   "other": "Ganesha mantras"},
        "deity": "Ganesha and Bhairava", "fast_day": "Tuesday",
        "donate": ["blankets", "sesame", "multi-coloured cloth", "food for dogs"], "donate_day": "Tuesday",
        "colour": "Brown or multi-coloured", "rudraksha": "9 Mukhi",
        "daily_practice": "Meditate for a few minutes daily and simplify what you own.",
        "folk_upaya": "Feed stray dogs, donate blankets and offer a flag at a Ganesha temple.",
    },
}

DOSHA_REMEDIES: dict[str, list[str]] = {
    "manglik": [
        "Chant the Hanuman Chalisa and fast on Tuesdays.",
        "Donate red lentils and red cloth on Tuesdays.",
        "A Mangal Shanti puja is the traditional ritual remedy.",
        "Practise patience and channel Martian energy into exercise or service.",
        "Traditionally, a Manglik partner is considered a balancing match.",
    ],
    "kaal_sarp": [
        "Chant the Maha Mrityunjaya mantra regularly.",
        "Offer milk and water to a Shivling on Mondays and on Nag Panchami.",
        "A Kaal Sarp Shanti puja at a traditional pilgrimage site (such as Trimbakeshwar or Ujjain) is customary.",
        "Donate to those in need on Saturdays and Amavasya.",
    ],
    "sade_sati": [
        "Chant the Hanuman Chalisa or Shani mantra on Saturdays.",
        "Light a mustard-oil lamp and donate black sesame or blankets on Saturdays.",
        "Serve elders, workers and the underprivileged; stay disciplined and punctual.",
        "Avoid wearing Blue Sapphire without a trial and expert advice.",
    ],
    "pitru": [
        "Perform Tarpan and Shraddha rites during Pitru Paksha.",
        "Feed the needy and Brahmins on Amavasya in the memory of ancestors.",
        "Plant and water a peepal tree; a Pitru Shanti puja is the traditional ritual remedy.",
    ],
    "grahan_surya": ["Offer water to the Sun daily and recite Aditya Hridayam.", "Donate wheat or jaggery on Sundays."],
    "grahan_chandra": ["Recite Chandra or Shiva mantras and perform abhishek on Mondays.", "Donate rice or milk on Mondays."],
    "guru_chandala": ["Respect your teachers and elders and fast on Thursdays.", "Recite Vishnu Sahasranama and donate yellow items."],
    "angarak": ["Worship Hanuman on Tuesdays and avoid arguments.", "Donate red lentils on Tuesdays."],
    "shrapit": ["Worship Shiva on Saturdays and recite Shani and Rahu mantras.", "Serve the needy without expecting return."],
    "vish": ["Perform Shiva abhishek on Mondays and recite the Hanuman Chalisa on Saturdays.", "Keep routines calm and seek supportive company."],
    "gand_mool": ["A Gand Mool Shanti puja is traditionally performed on the 27th day after birth, or when the birth nakshatra recurs."],
    "nadi": ["A Nadi Dosha Nivaran puja is the traditional remedy.", "Charity of grain, a cow or gold to the needy is customary."],
    "bhakoot": ["Chant the Maha Mrityunjaya mantra and perform a Bhakoot Dosha puja.", "Nurture emotional openness and shared goals."],
}


def planet_remedy(name: str) -> dict | None:
    return PLANET_REMEDIES.get(name)


def dosha_remedies(keys: list[str]) -> list[dict]:
    return [{"dosha": k, "remedies": DOSHA_REMEDIES[k]} for k in keys if k in DOSHA_REMEDIES]


def _ruled_house_numbers(chart, planet: str) -> list[int]:
    return [h.number for h in chart.houses if h.lord == planet]


def personal_remedies(chart, now: datetime | None = None, max_items: int = 5) -> dict:
    """Pick remedies by classical logic: strengthen weak benefics, pacify malefics, support the running dasha."""
    now = now or datetime.now(timezone.utc)
    tl = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    cur = D.period_at(tl, now.replace(tzinfo=None))
    running = {}
    if cur:
        running = {"mahadasha": cur["maha"]["lord"], "antardasha": cur["antar"]["lord"] if cur["antar"] else None}

    functional = chart.functional_nature
    asc_lord = chart.ascendant["lord"]
    candidates: dict[str, dict] = {}

    def add(planet: str, mode: str, why: str, priority: int) -> None:
        if planet not in PLANET_REMEDIES:
            return
        if planet not in candidates or priority > candidates[planet]["priority"]:
            candidates[planet] = {"planet": planet, "mode": mode, "why": why, "priority": priority}

    for planet in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"):
        st = S.planet_strength(chart, planet) if planet in chart.planets else None
        nature = functional.get(planet, "neutral")
        ruled = _ruled_house_numbers(chart, planet)
        in_dusthana_lord = bool(ruled) and all(h in (6, 8, 12) for h in ruled)
        if planet in running.values():
            role = "Mahadasha" if planet == running.get("mahadasha") else "Antardasha"
            can_gem = nature in ("benefic", "yogakaraka") and not in_dusthana_lord
            add(planet, "strengthen" if can_gem else "pacify",
                f"{planet} rules your current {role}; supporting it helps the whole period.", 80)
        if planet == asc_lord:
            add(planet, "strengthen", "Lagna lord: the planet of overall wellbeing, usually worth supporting.", 70)
        if st and st["label"] == "weak" and nature in ("benefic", "yogakaraka"):
            add(planet, "strengthen", f"{planet} is a functional benefic for your Lagna but looks weak ({'; '.join(st['notes'][:2])}).", 75)
        if st and nature == "malefic" and planet not in ("Rahu", "Ketu") and st["label"] != "weak":
            add(planet, "pacify", f"{planet} is a functional malefic with real strength; pacifying it softens its pressure.", 60)
        if planet in ("Rahu", "Ketu") and chart.planets[planet].house in (1, 4, 5, 7, 8, 9, 12):
            add(planet, "pacify", f"{planet} sits in a sensitive house ({chart.planets[planet].house}th); pacifying it brings steadiness.", 55)

    ranked = sorted(candidates.values(), key=lambda c: -c["priority"])[:max_items]
    items = []
    for c in ranked:
        rem = PLANET_REMEDIES[c["planet"]]
        entry = {
            "planet": c["planet"], "mode": c["mode"], "why": c["why"],
            "mantra": rem["mantra"], "deity": rem["deity"], "fast_day": rem["fast_day"],
            "donate": {"items": rem["donate"], "day": rem["donate_day"]},
            "colour": rem["colour"], "rudraksha": rem["rudraksha"],
            "daily_practice": rem["daily_practice"], "simple_upaya": rem["folk_upaya"],
        }
        if c["mode"] == "strengthen":
            entry["gemstone"] = rem["gemstone"]
        items.append(entry)
    return {"running_dasha": running, "remedies": items, "disclaimer": DISCLAIMER}
