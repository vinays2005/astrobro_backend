"""Vastu Shastra guidance: rule-based room-placement analysis. Traditional guidelines, not engineering advice."""
from __future__ import annotations

DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "CENTER"]
DIRECTION_NAMES = {
    "N": "North", "NE": "North-East", "E": "East", "SE": "South-East", "S": "South",
    "SW": "South-West", "W": "West", "NW": "North-West", "CENTER": "Centre (Brahmasthan)",
}
_ALIASES = {
    "NORTH": "N", "NORTHEAST": "NE", "NORTH-EAST": "NE", "EAST": "E", "SOUTHEAST": "SE", "SOUTH-EAST": "SE",
    "SOUTH": "S", "SOUTHWEST": "SW", "SOUTH-WEST": "SW", "WEST": "W", "NORTHWEST": "NW", "NORTH-WEST": "NW",
    "CENTRE": "CENTER", "CENTER": "CENTER", "MIDDLE": "CENTER", "BRAHMASTHAN": "CENTER",
}
_ELEMENT = {"N": "Water", "NE": "Water", "E": "Air", "SE": "Fire", "S": "Fire", "SW": "Earth",
            "W": "Space", "NW": "Air", "CENTER": "Space"}
_RULER = {"N": "Kubera", "NE": "Ishana", "E": "Indra", "SE": "Agni", "S": "Yama",
          "SW": "Nirriti", "W": "Varuna", "NW": "Vayu", "CENTER": "Brahma"}

# room -> {"ideal": [...], "acceptable": [...], "avoid": [...], "why": str, "remedy": str}
RULES: dict[str, dict] = {
    "main_entrance": {
        "label": "Main entrance", "ideal": ["N", "NE", "E"], "acceptable": ["NW", "SE"], "avoid": ["SW", "S"],
        "why": "North, north-east and east entrances welcome light and positive flow of energy.",
        "remedy": "Keep the entrance well lit, clean and uncluttered; a nameplate and auspicious toran help.",
    },
    "living_room": {
        "label": "Living room", "ideal": ["N", "NE", "E", "NW"], "acceptable": ["W"], "avoid": ["SW", "SE"],
        "why": "Light, open directions suit social spaces.", "remedy": "Place heavy furniture in the south or west of the room.",
    },
    "kitchen": {
        "label": "Kitchen", "ideal": ["SE"], "acceptable": ["NW"], "avoid": ["NE", "SW", "CENTER", "N"],
        "why": "The south-east belongs to Agni, the fire element.",
        "remedy": "Cook facing east; keep the stove away from the sink and avoid a kitchen in the north-east.",
    },
    "master_bedroom": {
        "label": "Master bedroom", "ideal": ["SW"], "acceptable": ["S", "W"], "avoid": ["NE", "SE", "CENTER"],
        "why": "The south-west gives stability and grounding for the head of the household.",
        "remedy": "Sleep with the head towards south or east; avoid mirrors facing the bed.",
    },
    "children_bedroom": {
        "label": "Children's bedroom", "ideal": ["W", "NW", "N"], "acceptable": ["E"], "avoid": ["SW", "SE"],
        "why": "West and north-west support activity and growth.", "remedy": "Place the study table in the east or north of the room.",
    },
    "guest_bedroom": {
        "label": "Guest bedroom", "ideal": ["NW"], "acceptable": ["W", "N"], "avoid": ["SW", "NE"],
        "why": "The north-west is the direction of movement and visitors.", "remedy": "Keep the room light and airy.",
    },
    "pooja_room": {
        "label": "Pooja room", "ideal": ["NE"], "acceptable": ["E", "N"], "avoid": ["S", "SW", "SE"],
        "why": "The north-east is the most sacred, light-filled zone.",
        "remedy": "Face east or north while praying; keep the space clean and avoid placing it near a toilet.",
    },
    "dining_room": {
        "label": "Dining room", "ideal": ["W", "E"], "acceptable": ["N", "SE"], "avoid": ["SW", "NE"],
        "why": "West and east suit meals and family gathering.", "remedy": "Keep the dining area close to the kitchen.",
    },
    "study_room": {
        "label": "Study room", "ideal": ["W", "NW", "NE", "E"], "acceptable": ["N"], "avoid": ["SW", "S"],
        "why": "These directions support focus and learning.", "remedy": "Face east or north while studying.",
    },
    "toilet": {
        "label": "Toilet / bathroom", "ideal": ["NW", "W"], "acceptable": ["S"], "avoid": ["NE", "SW", "SE", "CENTER", "E"],
        "why": "Toilets suit the north-west or west, away from sacred and central zones.",
        "remedy": "Keep the door closed and the space well ventilated; avoid a toilet in the north-east.",
    },
    "staircase": {
        "label": "Staircase", "ideal": ["S", "SW", "W"], "acceptable": ["SE", "NW"], "avoid": ["NE", "CENTER", "N"],
        "why": "Heavy structures suit the south and west.", "remedy": "Keep the stairs well lit and avoid an open centre.",
    },
    "underground_water_tank": {
        "label": "Underground water tank / borewell", "ideal": ["NE"], "acceptable": ["N", "E"], "avoid": ["SW", "SE", "S"],
        "why": "Water belongs to the north-east.", "remedy": "Avoid water storage in the south-west or south-east.",
    },
    "overhead_water_tank": {
        "label": "Overhead water tank", "ideal": ["W", "SW"], "acceptable": ["S", "NW"], "avoid": ["NE", "SE", "CENTER"],
        "why": "Heavy overhead loads suit the west and south-west.", "remedy": "Keep the tank clean and leak-free.",
    },
    "septic_tank": {
        "label": "Septic tank", "ideal": ["NW", "W"], "acceptable": ["N"], "avoid": ["NE", "SW", "SE", "CENTER"],
        "why": "Waste systems stay away from the north-east and the centre.", "remedy": "Keep it covered and well maintained.",
    },
    "safe_locker": {
        "label": "Safe / cash locker", "ideal": ["S", "SW", "W"], "acceptable": ["N"], "avoid": ["NE", "SE", "CENTER"],
        "why": "Valuables are placed in a heavy wall with the door opening towards the north (Kubera).",
        "remedy": "Place the safe against a south or west wall so that it opens to the north.",
    },
    "store_room": {
        "label": "Store room", "ideal": ["NW", "SW", "W"], "acceptable": ["S"], "avoid": ["NE", "CENTER"],
        "why": "Storage suits heavier directions.", "remedy": "Keep the north-east free and light.",
    },
    "garage": {
        "label": "Garage", "ideal": ["SE", "NW"], "acceptable": ["W", "S"], "avoid": ["NE", "SW"],
        "why": "Vehicles are linked with fire and air.", "remedy": "Park facing east or north where possible.",
    },
    "balcony": {
        "label": "Balcony", "ideal": ["N", "NE", "E"], "acceptable": ["NW"], "avoid": ["SW", "S"],
        "why": "Open spaces towards light and air are favourable.", "remedy": "Keep plants in the north-east and east.",
    },
    "office_cabin": {
        "label": "Office / owner's cabin", "ideal": ["SW", "S", "W"], "acceptable": ["NW"], "avoid": ["NE", "SE"],
        "why": "The owner's seat is stable and weighty in the south-west.", "remedy": "Sit facing north or east with a solid wall behind.",
    },
}

ENTRANCE_PADA_NOTE = (
    "Within each side of the plot, entrance placement in specific padas (subdivisions) matters in classical Vastu; "
    "a detailed pada analysis needs the plot plan."
)
GENERAL_TIPS = [
    "Keep the centre of the home (Brahmasthan) open, light and uncluttered.",
    "Let natural light and fresh air enter from the north and east.",
    "Avoid heavy structures and clutter in the north-east.",
    "Fix leaking taps and keep water flowing towards the north-east.",
    "Avoid beams over beds and seating where you spend long hours.",
    "Remember that Vastu is a traditional guideline system; comfort, safety and building codes come first.",
]


def normalize_direction(value: str) -> str:
    key = value.strip().upper().replace(" ", "")
    key = _ALIASES.get(key, key)
    if key not in DIRECTIONS:
        raise ValueError(f"Unknown direction '{value}'. Use N, NE, E, SE, S, SW, W, NW or CENTER.")
    return key


def normalize_room(value: str) -> str:
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in RULES:
        raise ValueError(f"Unknown room '{value}'. Supported: {', '.join(sorted(RULES))}")
    return key


def evaluate(room: str, direction: str) -> dict:
    r, d = normalize_room(room), normalize_direction(direction)
    rule = RULES[r]
    if d in rule["ideal"]:
        status, score = "ideal", 100
    elif d in rule["acceptable"]:
        status, score = "acceptable", 70
    elif d in rule["avoid"]:
        status, score = "avoid", 25
    else:
        status, score = "neutral", 50
    return {
        "room": r, "label": rule["label"], "direction": d, "direction_name": DIRECTION_NAMES[d],
        "element": _ELEMENT[d], "ruling_deity": _RULER[d],
        "status": status, "score": score,
        "ideal_directions": [DIRECTION_NAMES[x] for x in rule["ideal"]],
        "reason": rule["why"],
        "remedy": rule["remedy"] if status in ("avoid", "neutral") else None,
    }


def analyze(entrance_facing: str | None, rooms: dict[str, str]) -> dict:
    """rooms: {room_key: direction}. Entrance facing is checked as the main entrance."""
    findings = []
    if entrance_facing:
        findings.append(evaluate("main_entrance", entrance_facing))
    for room, direction in rooms.items():
        findings.append(evaluate(room, direction))
    scored = [f["score"] for f in findings]
    overall = round(sum(scored) / len(scored)) if scored else 0
    label = "very good" if overall >= 85 else "good" if overall >= 70 else "mixed" if overall >= 50 else "needs attention"
    return {
        "overall_score": overall, "overall_label": label,
        "ideal": [f for f in findings if f["status"] == "ideal"],
        "acceptable": [f for f in findings if f["status"] == "acceptable"],
        "needs_attention": [f for f in findings if f["status"] in ("avoid", "neutral")],
        "findings": findings,
        "general_tips": GENERAL_TIPS, "entrance_note": ENTRANCE_PADA_NOTE,
        "disclaimer": "Vastu guidance is traditional and non-structural. It is not a substitute for professional building advice.",
    }


def guidelines() -> dict:
    return {
        "directions": {k: {"name": DIRECTION_NAMES[k], "element": _ELEMENT[k], "ruling_deity": _RULER[k]} for k in DIRECTIONS},
        "rooms": {k: {"label": v["label"], "ideal": [DIRECTION_NAMES[d] for d in v["ideal"]],
                      "acceptable": [DIRECTION_NAMES[d] for d in v["acceptable"]],
                      "avoid": [DIRECTION_NAMES[d] for d in v["avoid"]], "why": v["why"]} for k, v in RULES.items()},
        "general_tips": GENERAL_TIPS,
    }
