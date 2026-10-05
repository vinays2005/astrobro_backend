"""Tarot: 78-card deck with original meanings, spreads, yes/no and card of the day. Deterministic given a seed."""
from __future__ import annotations

import random
import secrets
from datetime import date

# (number, name, element, upright keywords, reversed keywords, upright meaning, reversed meaning, love, career)
_MAJOR = [
    (0, "The Fool", "Air", ["new beginnings", "spontaneity", "trust"], ["recklessness", "hesitation", "naivety"],
     "A fresh start calls. Step forward with trust and curiosity.", "Acting without thought, or fear of the leap, holds you back.",
     "Stay open to a new connection without over-planning.", "A new direction or venture is available."),
    (1, "The Magician", "Air", ["willpower", "skill", "manifestation"], ["manipulation", "untapped talent", "poor planning"],
     "You have the tools you need. Focus your will and act.", "Talent goes unused or is misdirected; check your motives.",
     "Take initiative and communicate clearly.", "A strong moment to launch and show your skills."),
    (2, "The High Priestess", "Water", ["intuition", "mystery", "inner knowing"], ["secrets", "ignoring intuition", "surface thinking"],
     "Listen inward; the answer is already stirring beneath the surface.", "You are overlooking your intuition or something is hidden.",
     "Quiet observation will tell you more than words.", "Wait and gather information before acting."),
    (3, "The Empress", "Earth", ["abundance", "nurturing", "creativity"], ["dependence", "smothering", "creative block"],
     "Growth, comfort and creativity flourish. Nurture what you love.", "Overgiving, dependence or a creative drought.",
     "A warm, affectionate and fertile period in love.", "Creative projects and teamwork thrive."),
    (4, "The Emperor", "Fire", ["structure", "authority", "stability"], ["rigidity", "control", "domination"],
     "Build order and take responsibility. Steady leadership wins.", "Control turns to rigidity, or authority is misused.",
     "Commitment and reliability are valued.", "Lead with clear structure and boundaries."),
    (5, "The Hierophant", "Earth", ["tradition", "guidance", "shared values"], ["rebellion", "dogma", "unconventional path"],
     "Learn from tradition, mentors and shared values.", "Question rigid rules, or find your own way of believing.",
     "A relationship moving towards commitment or family approval.", "Follow the established route or seek a mentor."),
    (6, "The Lovers", "Air", ["love", "union", "choices"], ["disharmony", "misalignment", "indecision"],
     "A meaningful connection or a choice made from the heart.", "Values are out of line or a choice is being avoided.",
     "Deep attraction and a decision about commitment.", "Align your work with your values."),
    (7, "The Chariot", "Water", ["determination", "victory", "control"], ["lack of direction", "aggression", "setbacks"],
     "Drive and discipline carry you to victory.", "Scattered effort or force without direction.",
     "Move forward with confidence, but stay considerate.", "Strong momentum; stay focused on the goal."),
    (8, "Strength", "Fire", ["courage", "patience", "inner strength"], ["self-doubt", "insecurity", "raw emotion"],
     "Gentle courage and patience tame even the fiercest challenge.", "Doubt drains your confidence; rebuild from within.",
     "Compassion and patience deepen the bond.", "Persevere calmly; quiet strength wins."),
    (9, "The Hermit", "Earth", ["solitude", "reflection", "guidance"], ["isolation", "loneliness", "withdrawal"],
     "Step back and seek your own truth.", "Isolation has gone too far, or you resist reflection.",
     "Time alone brings clarity about what you want.", "Study, plan and seek wisdom before acting."),
    (10, "Wheel of Fortune", "Fire", ["change", "cycles", "destiny"], ["bad luck", "resistance to change", "delays"],
     "Life turns; a favourable change or cycle arrives.", "A setback or a refusal to adapt to change.",
     "A fated turn; go with the flow.", "A shift in fortune; stay adaptable."),
    (11, "Justice", "Air", ["fairness", "truth", "accountability"], ["injustice", "dishonesty", "avoiding responsibility"],
     "Truth and fair outcomes prevail; own your choices.", "Unfair treatment or avoided accountability.",
     "Honesty and balance matter in love.", "Contracts and decisions need careful, fair review."),
    (12, "The Hanged Man", "Water", ["pause", "surrender", "new perspective"], ["stalling", "resistance", "needless sacrifice"],
     "Pause and look at things differently; surrender brings insight.", "Stalling or sacrificing without purpose.",
     "Patience; see the relationship from a new angle.", "A delay that offers a better view."),
    (13, "Death", "Water", ["endings", "transformation", "release"], ["resistance to change", "stagnation", "fear of letting go"],
     "An ending clears space for renewal.", "Clinging to what is over delays the next chapter.",
     "A chapter closes, making room for renewal.", "A role or job phase ends; transformation follows."),
    (14, "Temperance", "Fire", ["balance", "moderation", "harmony"], ["excess", "imbalance", "impatience"],
     "Blend and balance; patience brings harmony.", "Excess or imbalance disturbs your progress.",
     "Balanced, healing, gradual progress.", "Collaborate and keep a steady pace."),
    (15, "The Devil", "Earth", ["attachment", "temptation", "bondage"], ["release", "breaking free", "reclaiming power"],
     "Notice what binds you, such as habits, fears or unhealthy attachments.", "You are loosening chains and reclaiming your power.",
     "Unhealthy attachment or obsession needs honesty.", "Beware golden handcuffs and overwork."),
    (16, "The Tower", "Fire", ["upheaval", "sudden change", "revelation"], ["averting disaster", "fear of change", "aftermath"],
     "Sudden change shakes false foundations and reveals truth.", "A narrow escape or a slow, fearful rebuilding.",
     "A shake-up that exposes what is not real.", "Unexpected change; rebuild on firmer ground."),
    (17, "The Star", "Air", ["hope", "healing", "inspiration"], ["discouragement", "faithlessness", "disconnection"],
     "Hope returns and healing is under way.", "Hope feels distant; reconnect with what inspires you.",
     "Renewed trust and gentle optimism.", "Inspiration and recognition after a hard period."),
    (18, "The Moon", "Water", ["illusion", "intuition", "the unconscious"], ["clarity", "release of fear", "truth emerging"],
     "Things are not as clear as they seem; trust intuition and go slowly.", "Fog lifts and hidden fears or secrets come to light.",
     "Mixed signals; wait for clarity before deciding.", "Information is incomplete; avoid rash moves."),
    (19, "The Sun", "Fire", ["joy", "success", "vitality"], ["temporary clouds", "overconfidence", "delayed success"],
     "Warmth, success and clarity shine on you.", "Joy is dimmed for now or confidence runs too high.",
     "Happiness, openness and warmth in love.", "Success and visible achievement."),
    (20, "Judgement", "Fire", ["awakening", "reckoning", "renewal"], ["self-doubt", "ignoring the call", "harsh self-judgement"],
     "A call to rise, forgive and begin anew.", "Self-criticism or ignoring an important call.",
     "Forgiveness and a fresh start.", "A turning point; answer your calling."),
    (21, "The World", "Earth", ["completion", "fulfilment", "wholeness"], ["unfinished business", "shortcuts", "lack of closure"],
     "A cycle completes in success and wholeness.", "Something remains unfinished; tie up loose ends.",
     "Feeling whole and complete together.", "A project reaches its goal; the next stage opens."),
]

_SUITS = {
    "Wands": ("Fire", "passion, drive and career"),
    "Cups": ("Water", "emotions, love and relationships"),
    "Swords": ("Air", "thoughts, truth and conflict"),
    "Pentacles": ("Earth", "money, work and health"),
}
_RANKS = ["Ace", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Page", "Knight", "Queen", "King"]

# per suit: (upright keywords, reversed keywords, upright meaning, reversed meaning) for each rank
_MINOR: dict[str, list[tuple[list[str], list[str], str, str]]] = {
    "Wands": [
        (["inspiration", "new spark", "potential"], ["delays", "lack of direction", "burnout"], "A surge of creative energy and a new opportunity begins.", "A promising start stalls through doubt or poor timing."),
        (["planning", "decisions", "vision"], ["fear of change", "poor planning", "staying put"], "Plan your next bold step; the world is in your hands.", "Fear of the unknown or weak planning keeps you stuck."),
        (["expansion", "foresight", "progress"], ["delays", "obstacles", "frustration"], "Efforts begin to pay off; look to wider horizons.", "Plans meet delays; patience and a revised approach are needed."),
        (["celebration", "harmony", "home"], ["instability", "tension at home", "delayed celebration"], "A moment of joy, stability and community.", "Tension at home or a celebration postponed."),
        (["competition", "conflict", "tension"], ["avoiding conflict", "resolution", "inner turmoil"], "Clashing ideas and rivalry; healthy competition can sharpen you.", "Conflict eases or is being avoided; resolution is possible."),
        (["victory", "recognition", "confidence"], ["ego", "fall from grace", "lack of recognition"], "Success and public recognition after effort.", "Pride or a dent in recognition; stay humble."),
        (["defending", "perseverance", "standing ground"], ["overwhelm", "giving up", "exhaustion"], "Hold your position; you have the advantage.", "Feeling overwhelmed; choose your battles."),
        (["speed", "movement", "messages"], ["delays", "slowdown", "scattered energy"], "Things move fast; news and action arrive quickly.", "Slowdowns and mixed signals; avoid rushing."),
        (["resilience", "persistence", "last stand"], ["exhaustion", "defensiveness", "paranoia"], "Nearly there; keep going despite fatigue.", "Weariness and wariness; rest before the final push."),
        (["burden", "responsibility", "hard work"], ["delegating", "release", "burnout"], "You carry a lot; ask whether every load is yours.", "Putting a burden down and learning to delegate."),
        (["enthusiasm", "exploration", "new ideas"], ["impatience", "lack of direction", "hesitation"], "A curious, energetic message or beginner's spark.", "Restless ideas without follow-through."),
        (["adventure", "passion", "action"], ["recklessness", "impatience", "burnout"], "Bold, energetic pursuit of a goal.", "Haste and scattered energy cause setbacks."),
        (["confidence", "warmth", "determination"], ["jealousy", "insecurity", "demanding"], "Magnetic confidence and generous drive.", "Insecurity or temper dims your glow."),
        (["vision", "leadership", "entrepreneurship"], ["impulsiveness", "domineering", "unrealistic goals"], "An inspiring leader who turns vision into action.", "Domineering or impulsive leadership."),
    ],
    "Cups": [
        (["new love", "compassion", "emotional start"], ["blocked feelings", "emptiness", "repression"], "A wave of emotion, love or creativity opens.", "Feelings are held back or unreturned."),
        (["partnership", "attraction", "mutual respect"], ["imbalance", "disconnection", "breakup"], "A balanced, loving connection.", "A bond out of balance, or communication breaking down."),
        (["friendship", "celebration", "community"], ["overindulgence", "gossip", "isolation"], "Joyful gatherings and supportive friends.", "Excess, gossip or feeling left out."),
        (["apathy", "contemplation", "reevaluation"], ["new awareness", "acceptance", "motivation returns"], "Boredom or missed offers; look again at what is before you.", "You wake up to new possibilities."),
        (["loss", "regret", "grief"], ["acceptance", "moving on", "finding peace"], "Focus on what is lost; remember what remains.", "You begin to heal and move forward."),
        (["nostalgia", "childhood", "kindness"], ["stuck in the past", "naivety", "unrealistic memories"], "Sweet memories and simple kindness.", "Living in the past blocks growth."),
        (["choices", "fantasy", "illusion"], ["clarity", "decision", "reality check"], "Many options and daydreams; separate fantasy from reality.", "Illusions fade and a clear choice emerges."),
        (["walking away", "disillusionment", "seeking more"], ["fear of change", "aimless drifting", "staying too long"], "You leave what no longer satisfies to seek meaning.", "Hesitation about leaving, or wandering without purpose."),
        (["contentment", "wish fulfilled", "satisfaction"], ["smugness", "greed", "dissatisfaction"], "The wish card: emotional and material satisfaction.", "Indulgence or hollow satisfaction."),
        (["harmony", "family joy", "fulfilment"], ["broken home", "disharmony", "misaligned values"], "Lasting emotional happiness and a loving home.", "Family or values out of alignment."),
        (["gentle message", "creativity", "intuition"], ["emotional immaturity", "moodiness", "blocked creativity"], "A tender message or creative idea arrives.", "Moodiness or ignoring your intuition."),
        (["romance", "charm", "offers"], ["unrealistic", "moodiness", "jealousy"], "A romantic offer or idealistic pursuit.", "Charm without substance; keep expectations realistic."),
        (["compassion", "intuition", "emotional security"], ["emotional overwhelm", "martyrdom", "insecurity"], "Warm, intuitive care for yourself and others.", "Overgiving or emotional overwhelm."),
        (["emotional balance", "wisdom", "diplomacy"], ["manipulation", "moodiness", "coldness"], "Calm, wise mastery of emotions.", "Emotional manipulation or suppression."),
    ],
    "Swords": [
        (["clarity", "truth", "breakthrough"], ["confusion", "harshness", "clouded judgement"], "A moment of mental clarity and a decisive idea.", "Confusion or harsh words cloud the truth."),
        (["stalemate", "difficult choice", "avoidance"], ["indecision", "information overload", "release"], "A hard decision you are avoiding; weigh the facts.", "The choice can no longer be postponed."),
        (["heartbreak", "sorrow", "painful truth"], ["recovery", "forgiveness", "moving on"], "Painful truth or emotional pain.", "Healing begins as you release the hurt."),
        (["rest", "restoration", "recuperation"], ["restlessness", "burnout", "returning to activity"], "Pause and recharge.", "Restlessness, or a return to activity."),
        (["conflict", "tension", "hollow victory"], ["reconciliation", "regret", "letting go"], "A win at a cost; pick battles wisely.", "Making peace, or regretting the fight."),
        (["transition", "moving on", "calmer waters"], ["emotional baggage", "stuck", "resistance to change"], "A gentle move towards better times.", "Carrying baggage you need to unpack."),
        (["strategy", "stealth", "deception"], ["confession", "conscience", "rethinking"], "Acting alone or on the sly; be honest with yourself.", "Truth emerges or a plan is rethought."),
        (["restriction", "feeling trapped", "self-limiting beliefs"], ["freedom", "new perspective", "self-acceptance"], "You feel stuck, though many limits are mental.", "Release self-imposed limits."),
        (["anxiety", "worry", "sleepless nights"], ["hope", "reaching out", "despair easing"], "Worry magnifies fears; talk it through.", "Anxiety lifts as you seek support."),
        (["endings", "rock bottom", "betrayal"], ["recovery", "resilience", "slow healing"], "A painful ending that clears the ground.", "The worst is over; healing starts."),
        (["curiosity", "vigilance", "new ideas"], ["gossip", "haste", "scattered thoughts"], "A sharp mind eager to learn.", "Careless words or restless thoughts."),
        (["ambition", "fast action", "drive"], ["impulsive", "aggressive", "no direction"], "Charging towards a goal with focus.", "Rushing in without thinking."),
        (["independence", "clear boundaries", "perceptive"], ["coldness", "bitterness", "harsh judgement"], "Honest, clear-eyed independence.", "Cutting words or emotional distance."),
        (["intellectual authority", "truth", "fairness"], ["abuse of power", "manipulation", "tyranny"], "Reasoned, fair leadership.", "Cold or manipulative authority."),
    ],
    "Pentacles": [
        (["opportunity", "prosperity", "new venture"], ["missed chance", "scarcity", "poor planning"], "A tangible chance for security or a new venture.", "A missed or badly planned opportunity."),
        (["balance", "adaptability", "juggling priorities"], ["overwhelm", "disorganisation", "poor balance"], "Juggle priorities with flexibility.", "Dropped balls and financial strain."),
        (["teamwork", "skill", "collaboration"], ["disharmony", "poor quality", "lack of teamwork"], "Skill and cooperation build something lasting.", "Miscommunication or shoddy work."),
        (["security", "saving", "control"], ["greed", "materialism", "letting go"], "Holding on to what you have; avoid hoarding.", "Loosening an over-tight grip."),
        (["hardship", "insecurity", "exclusion"], ["recovery", "help arrives", "spiritual wealth"], "Financial or emotional hardship; help is closer than it seems.", "Recovery and finding support."),
        (["generosity", "sharing", "fairness"], ["debt", "strings attached", "one-sided giving"], "Giving and receiving in balance.", "Imbalance in giving, or hidden obligations."),
        (["patience", "long-term view", "assessment"], ["impatience", "poor returns", "wasted effort"], "Pause to assess; the harvest takes time.", "Frustration at slow returns."),
        (["craftsmanship", "diligence", "skill building"], ["perfectionism", "lack of focus", "uninspired work"], "Dedicated practice and quality work.", "Perfectionism or boredom."),
        (["independence", "luxury", "self-sufficiency"], ["overworking", "financial dependence", "hollow success"], "Earned comfort and self-reliance.", "Success without enjoyment, or dependence."),
        (["legacy", "wealth", "family security"], ["family disputes", "financial failure", "instability"], "Lasting security and family prosperity.", "Disputes over money or shaky foundations."),
        (["study", "opportunity", "ambition"], ["procrastination", "lack of progress", "impractical"], "A student of life with a new practical goal.", "Daydreams that never become plans."),
        (["reliability", "hard work", "routine"], ["boredom", "stagnation", "laziness"], "Slow, steady progress.", "Stuck in routine or complacent."),
        (["nurturing", "practicality", "abundance"], ["self-neglect", "jealousy", "smothering"], "Generous, practical care.", "Neglecting yourself, or being overbearing."),
        (["wealth", "stability", "reliability"], ["greed", "stubbornness", "poor money sense"], "A secure, generous provider.", "Possessiveness or financial recklessness."),
    ],
}

_POSITIVE = {
    "The Fool", "The Magician", "The Empress", "The Emperor", "The Lovers", "The Chariot", "Strength",
    "Wheel of Fortune", "Justice", "Temperance", "The Star", "The Sun", "Judgement", "The World",
    "Ace of Wands", "Ace of Cups", "Ace of Swords", "Ace of Pentacles", "Three of Wands", "Six of Wands",
    "Two of Cups", "Three of Cups", "Nine of Cups", "Ten of Cups", "Three of Pentacles", "Six of Pentacles",
    "Nine of Pentacles", "Ten of Pentacles", "Four of Wands", "Knight of Cups", "Queen of Cups", "King of Cups",
    "Queen of Pentacles", "King of Pentacles", "Queen of Wands", "King of Wands",
}
_NEGATIVE = {
    "Death", "The Devil", "The Tower", "Three of Swords", "Five of Swords", "Eight of Swords", "Nine of Swords",
    "Ten of Swords", "Five of Cups", "Five of Pentacles", "Seven of Swords", "Four of Cups", "Ten of Wands",
}

SPREADS: dict[str, list[str]] = {
    "single": ["Your card"],
    "three_card": ["Past", "Present", "Future"],
    "yes_no": ["Answer"],
    "love": ["You", "Your partner or desire", "The connection", "The challenge", "The outcome"],
    "career": ["Current situation", "The obstacle", "Hidden factor", "Advice", "The outcome"],
    "decision": ["Option A", "Option B", "Guidance"],
    "celtic_cross": ["The present", "The challenge", "The foundation", "The past", "The crown", "The near future",
                     "Yourself", "Your environment", "Hopes and fears", "The outcome"],
}


_POSITION_FRAMES = {
    "Your card": "This is the energy to reflect on right now.",
    "Answer": "Read this card as the direct answer to your question.",
    "Past": "This describes what has shaped the situation.",
    "Present": "This describes where you stand now.",
    "Future": "This shows the direction things are heading.",
    "You": "This is how you are showing up in the situation.",
    "Your partner or desire": "This reflects the other person or what you are drawn to.",
    "The connection": "This describes the dynamic between you.",
    "The challenge": "Read this as what stands in the way or needs attention; even a pleasant card can warn against complacency.",
    "The obstacle": "Read this as what stands in the way or needs attention; even a pleasant card can warn against complacency.",
    "Hidden factor": "This is something working beneath the surface.",
    "Current situation": "This describes where things stand at present.",
    "Advice": "Read this card as guidance to follow.",
    "Guidance": "Read this card as guidance to follow.",
    "Option A": "This shows what choosing the first path may bring.",
    "Option B": "This shows what choosing the second path may bring.",
    "The outcome": "This is the likely result if things continue as they are.",
    "The present": "This is the heart of the matter.",
    "The foundation": "This is the root or basis of the situation.",
    "The past": "This is what is receding.",
    "The crown": "This is your goal or best possible outcome.",
    "The near future": "This is what is approaching soon.",
    "Yourself": "This is your own position and attitude.",
    "Your environment": "This describes the influence of people and surroundings.",
    "Hopes and fears": "This reveals what you wish for and dread.",
}


def _build_deck() -> list[dict]:
    deck: list[dict] = []
    for num, name, element, ku, kr, up, rev, love, career in _MAJOR:
        deck.append({
            "id": f"major-{num:02d}", "number": num, "name": name, "arcana": "major", "suit": None,
            "element": element, "upright_keywords": ku, "reversed_keywords": kr,
            "upright": up, "reversed": rev, "love": love, "career": career,
        })
    for suit, (element, domain) in _SUITS.items():
        for i, rank in enumerate(_RANKS):
            ku, kr, up, rev = _MINOR[suit][i]
            deck.append({
                "id": f"{suit.lower()}-{i + 1:02d}", "number": i + 1, "name": f"{rank} of {suit}", "arcana": "minor",
                "suit": suit, "element": element, "upright_keywords": ku, "reversed_keywords": kr,
                "upright": up, "reversed": rev, "domain": domain,
            })
    return deck


DECK: list[dict] = _build_deck()
_BY_ID = {c["id"]: c for c in DECK}


def get_card(card_id: str) -> dict | None:
    return _BY_ID.get(card_id)


def tone(card: dict, reversed_: bool) -> int:
    base = 1 if card["name"] in _POSITIVE else -1 if card["name"] in _NEGATIVE else 0
    return -base if reversed_ else base


def _area_line(card: dict, reversed_: bool, area: str | None) -> str | None:
    if area not in ("love", "career"):
        return None
    if card["arcana"] == "major":
        line = card[area]
        return line if not reversed_ else f"Reversed: {line[0].lower() + line[1:]} Expect this to be delayed or blocked."
    kw = ", ".join((card["reversed_keywords"] if reversed_ else card["upright_keywords"])[:2])
    topic = "your love life" if area == "love" else "your work"
    return f"For {topic}, this card points to {kw}."


def _position_reading(position: str, card: dict, reversed_: bool, area: str | None) -> dict:
    kws = card["reversed_keywords"] if reversed_ else card["upright_keywords"]
    return {
        "position": position,
        "position_meaning": _POSITION_FRAMES.get(position, ""),
        "card": {"id": card["id"], "name": card["name"], "arcana": card["arcana"], "suit": card["suit"],
                 "element": card["element"]},
        "reversed": reversed_,
        "orientation": "Reversed" if reversed_ else "Upright",
        "keywords": kws,
        "meaning": card["reversed"] if reversed_ else card["upright"],
        "area_note": _area_line(card, reversed_, area),
        "tone": tone(card, reversed_),
    }


def _overall(readings: list[dict]) -> dict:
    majors = sum(1 for r in readings if r["card"]["arcana"] == "major")
    suits: dict[str, int] = {}
    for r in readings:
        if r["card"]["suit"]:
            suits[r["card"]["suit"]] = suits.get(r["card"]["suit"], 0) + 1
    score = sum(r["tone"] for r in readings)
    mood = "favourable" if score > 0 else "challenging" if score < 0 else "mixed"
    notes = []
    if majors >= max(2, len(readings) // 2):
        notes.append("Several Major Arcana cards suggest significant, life-shaping themes.")
    if suits:
        top, n = max(suits.items(), key=lambda kv: kv[1])
        if n >= 2:
            notes.append(f"Repeated {top} highlights {_SUITS[top][1]}.")
    rev = sum(1 for r in readings if r["reversed"])
    if rev > len(readings) / 2:
        notes.append("Many reversed cards point to inner work, delays or blocked energy.")
    return {"energy": mood, "notes": notes}


def draw(spread: str = "three_card", question: str | None = None, seed: str | int | None = None,
         allow_reversed: bool = True, area: str | None = None) -> dict:
    if spread not in SPREADS:
        raise ValueError(f"Unknown spread '{spread}'. Choose from: {', '.join(SPREADS)}")
    rng = random.Random(str(seed)) if seed is not None else secrets.SystemRandom()
    positions = SPREADS[spread]
    cards = rng.sample(DECK, len(positions))
    if area is None and spread in ("love", "career"):
        area = spread
    readings = []
    for pos, card in zip(positions, cards):
        readings.append(_position_reading(pos, card, allow_reversed and rng.random() < 0.35, area))
    out = {
        "spread": spread, "question": question, "reproducible": seed is not None,
        "readings": readings, "overall": _overall(readings),
        "disclaimer": "Tarot is a tool for reflection and entertainment, not a prediction of fact.",
    }
    if spread == "yes_no":
        r = readings[0]
        out["answer"] = {"result": "Yes" if r["tone"] > 0 else "No" if r["tone"] < 0 else "Maybe",
                         "explanation": r["meaning"]}
    return out


def card_of_the_day(on: date, user_key: str = "") -> dict:
    result = draw("single", seed=f"{on.isoformat()}|{user_key}")
    result["date"] = on.isoformat()
    return result
