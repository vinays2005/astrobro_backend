"""Extended dosha analysis from a natal Chart. Deterministic; severity is indicative, not a verdict."""
from __future__ import annotations

from datetime import datetime, timezone

from app.astrology import transits as T
from app.astrology.constants import NAKSHATRAS, SIGNS

_MANGLIK_HOUSES = {1, 2, 4, 7, 8, 12}
# Sign names where Mars in a given house (from Lagna) is classically considered self-cancelling
_MANGLIK_PARIHARA_SIGNS = {2: {2, 5}, 4: {0, 7}, 7: {3, 9}, 8: {8, 11}, 12: {1, 6}}
_KAALSARP_TYPES = {
    1: "Anant", 2: "Kulik", 3: "Vasuki", 4: "Shankhpal", 5: "Padma", 6: "Mahapadma",
    7: "Takshak", 8: "Karkotak", 9: "Shankhchud", 10: "Ghatak", 11: "Vishdhar", 12: "Sheshnag",
}
_KAALSARP_EFFECT = {
    1: "self-image and health", 2: "wealth and family", 3: "courage and siblings",
    4: "home and peace of mind", 5: "children and creativity", 6: "health and debts",
    7: "marriage and partnership", 8: "sudden events and longevity", 9: "luck and the father",
    10: "career and status", 11: "gains and friendships", 12: "expenses and isolation",
}
_GAND_MOOL = {"Ashwini", "Ashlesha", "Magha", "Jyeshtha", "Mula", "Revati"}
_PITRU_NODES = ("Rahu", "Ketu")


def _sign_idx(chart, name: str) -> int:
    return int(chart.planets[name].longitude / 30) % 12


def _house_from(chart, name: str, ref_sign: int) -> int:
    return ((_sign_idx(chart, name) - ref_sign) % 12) + 1


def _same_sign(chart, a: str, b: str) -> bool:
    return a in chart.planets and b in chart.planets and _sign_idx(chart, a) == _sign_idx(chart, b)


def _orb(chart, a: str, b: str) -> float:
    d = abs(chart.planets[a].longitude - chart.planets[b].longitude) % 360
    return 360 - d if d > 180 else d


def _aspects(chart, caster: str, target: str) -> bool:
    """Parashari drishti: all planets 7th; Mars 4/8, Jupiter 5/9, Saturn 3/10 additionally."""
    extra = {"Mars": (4, 8), "Jupiter": (5, 9), "Saturn": (3, 10)}.get(caster, ())
    h = ((_sign_idx(chart, target) - _sign_idx(chart, caster)) % 12) + 1
    return h == 7 or h in extra


def _item(name: str, present: bool, severity: str, reason: str, remedy_key: str,
          cancellations: list[str] | None = None, **extra) -> dict:
    cancellations = cancellations or []
    effective = severity if not cancellations else "reduced"
    return {
        "name": name, "present": present,
        "severity": "none" if not present else effective,
        "reason": reason if present else "", "cancellations": cancellations if present else [],
        "remedy_key": remedy_key, **extra,
    }


# ── Individual doshas ─────────────────────────────────────────────────────────

def manglik(chart) -> dict:
    asc = chart.ascendant["sign_index"]
    refs = {
        "Lagna": chart.planets["Mars"].house,
        "Moon": _house_from(chart, "Mars", _sign_idx(chart, "Moon")),
        "Venus": _house_from(chart, "Mars", _sign_idx(chart, "Venus")),
    }
    hits = {k: h for k, h in refs.items() if h in _MANGLIK_HOUSES}
    lagna_house = refs["Lagna"]
    mars_sign = _sign_idx(chart, "Mars")

    if "Lagna" not in hits and not hits:
        return _item("Manglik (Kuja) Dosha", False, "none", "", "manglik", mars_house=lagna_house, references=refs)

    if "Lagna" in hits and lagna_house in (7, 8):
        sev = "high"
    elif "Lagna" in hits and len(hits) >= 2:
        sev = "high"
    elif "Lagna" in hits and lagna_house == 2:
        sev = "low"
    elif "Lagna" in hits:
        sev = "moderate"
    else:
        sev = "low"  # only from Moon/Venus

    cancel: list[str] = []
    if mars_sign in (0, 7):
        cancel.append("Mars is in its own sign")
    if mars_sign == 9:
        cancel.append("Mars is exalted in Capricorn")
    if lagna_house in _MANGLIK_PARIHARA_SIGNS and mars_sign in _MANGLIK_PARIHARA_SIGNS[lagna_house]:
        cancel.append(f"Mars in {SIGNS[mars_sign]} in the {T._ORD[lagna_house]} house is a classical exception")
    if _same_sign(chart, "Jupiter", "Mars"):
        cancel.append("Jupiter is conjunct Mars")
    elif _aspects(chart, "Jupiter", "Mars"):
        cancel.append("Jupiter aspects Mars")
    if _same_sign(chart, "Moon", "Mars"):
        cancel.append("The Moon is conjunct Mars")
    saturn_house = chart.planets["Saturn"].house
    mitigating = []
    if saturn_house in _MANGLIK_HOUSES:
        mitigating.append("Saturn also occupies a Manglik house, which classically balances Mars")

    where = ", ".join(f"{k} ({T._ORD[h]} house)" for k, h in hits.items())
    return _item(
        "Manglik (Kuja) Dosha", True, sev,
        f"Mars falls in a Manglik house when counted from: {where}.",
        "manglik", cancel, mars_house=lagna_house, references=refs, mitigating_factors=mitigating,
    )


def kaal_sarp(chart) -> dict:
    rahu, ketu = chart.planets["Rahu"], chart.planets["Ketu"]
    seven = [p for p in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")]

    def in_arc(lon: float) -> bool:
        return ((lon - rahu.longitude) % 360) < 180

    inside = [p for p in seven if in_arc(chart.planets[p].longitude)]
    full = len(inside) in (0, 7)
    partial = not full and len(inside) in (1, 6)
    rahu_house = rahu.house
    if not full and not partial:
        return _item("Kaal Sarp Dosha", False, "none", "", "kaal_sarp", partial=False, type=None)
    kind = _KAALSARP_TYPES[rahu_house]
    reason = (f"All seven planets lie on one side of the Rahu-Ketu axis; Rahu is in the {rahu_house}th house, "
              f"giving {kind} Kaal Sarp Yoga, which classically colours {_KAALSARP_EFFECT[rahu_house]}."
              if full else
              f"Six planets lie on one side of the Rahu-Ketu axis (partial Kaal Sarp, {kind} type); "
              "the effect is milder because one planet breaks the arc.")
    return _item("Kaal Sarp Dosha", True, "high" if full else "low", reason, "kaal_sarp",
                 partial=partial, type=kind, rahu_house=rahu_house)


def pitru(chart) -> dict:
    score, reasons = 0, []
    sun = chart.planets["Sun"]
    for n in _PITRU_NODES:
        if _same_sign(chart, "Sun", n):
            score += 2
            reasons.append(f"Sun is conjunct {n}")
    if _same_sign(chart, "Sun", "Saturn"):
        score += 1
        reasons.append("Sun is conjunct Saturn")
    if sun.house == 9 and (_aspects(chart, "Saturn", "Sun") or any(_same_sign(chart, "Sun", n) for n in _PITRU_NODES)):
        score += 1
        reasons.append("Sun in the 9th house is afflicted")
    for n in _PITRU_NODES:
        if chart.planets[n].house == 9:
            score += 2
            reasons.append(f"{n} occupies the 9th house")
    ninth = chart.houses[8]
    lord = ninth.lord
    if lord in chart.planets:
        if any(_same_sign(chart, lord, n) for n in _PITRU_NODES) or (lord != "Saturn" and _same_sign(chart, lord, "Saturn")):
            score += 1
            reasons.append(f"The 9th lord {lord} is conjunct a malefic")
        if chart.planets[lord].house in (6, 8, 12):
            score += 1
            reasons.append(f"The 9th lord {lord} sits in a dusthana ({chart.planets[lord].house}th house)")
    if _same_sign(chart, "Jupiter", "Rahu"):
        score += 1
        reasons.append("Jupiter is conjunct Rahu")
    present = score >= 2
    sev = "high" if score >= 4 else "moderate"
    return _item("Pitru Dosha", present, sev, "; ".join(reasons) + ".", "pitru", score=score)


def grahan(chart) -> list[dict]:
    out = []
    for lum, label in (("Sun", "Surya Grahan Dosha"), ("Moon", "Chandra Grahan Dosha")):
        node = next((n for n in _PITRU_NODES if _same_sign(chart, lum, n)), None)
        if node:
            orb = _orb(chart, lum, node)
            out.append(_item(label, True, "high" if orb <= 10 else "moderate",
                             f"{lum} is conjunct {node} ({orb:.1f} degrees apart).",
                             "grahan_surya" if lum == "Sun" else "grahan_chandra", orb=round(orb, 1)))
        else:
            out.append(_item(label, False, "none", "", "grahan_surya" if lum == "Sun" else "grahan_chandra"))
    return out


def _conjunction(chart, a: str, b: str, name: str, key: str, text: str) -> dict:
    if _same_sign(chart, a, b):
        orb = _orb(chart, a, b)
        return _item(name, True, "high" if orb <= 10 else "moderate", f"{a} and {b} share a sign ({orb:.1f} degrees apart). {text}",
                     key, orb=round(orb, 1))
    return _item(name, False, "none", "", key)


def gand_mool(chart) -> dict:
    nak = chart.nakshatra_moon.name
    present = nak in _GAND_MOOL
    return _item("Gand Mool Dosha", present, "moderate",
                 f"The Moon is in {nak}, one of the six Gand Mool nakshatras (pada {chart.nakshatra_moon.pada}).",
                 "gand_mool", nakshatra=nak)


def sade_sati(chart, now: datetime | None = None) -> dict:
    moon_sign = _sign_idx(chart, "Moon")
    tl = T.sade_sati_timeline(moon_sign, now or datetime.now(timezone.utc))
    cur = tl["current"]
    nxt = next((p for p in tl["periods"] if p["start"] > (now or datetime.now(timezone.utc)).date().isoformat()
                and p["type"] == "sade_sati"), None)
    present = bool(cur and cur["type"] == "sade_sati")
    item = _item("Sade Sati", present, "high" if present and "Peak" in cur["phase"] else "moderate",
                 f"Saturn is in the {cur['phase']} phase ({cur['start']} to {cur['end']})." if present else "",
                 "sade_sati", current=cur, next_period=nxt, periods=tl["periods"])
    if cur and cur["type"] == "dhaiya":
        item["dhaiya"] = cur
    return item


# ── Entry point ───────────────────────────────────────────────────────────────

def analyze(chart, now: datetime | None = None) -> dict:
    items = [
        manglik(chart), kaal_sarp(chart), sade_sati(chart, now), pitru(chart),
        *grahan(chart),
        _conjunction(chart, "Jupiter", "Rahu", "Guru Chandala Dosha", "guru_chandala",
                     "Wisdom and judgement can be clouded; guidance from a teacher helps."),
        _conjunction(chart, "Mars", "Rahu", "Angarak Dosha", "angarak",
                     "Impulsiveness and anger need conscious control."),
        _conjunction(chart, "Saturn", "Rahu", "Shrapit Dosha", "shrapit",
                     "Delays and karmic lessons are emphasised."),
        _conjunction(chart, "Moon", "Saturn", "Vish Dosha", "vish",
                     "Emotional heaviness or pessimism may need care."),
        gand_mool(chart),
    ]
    present = [i["name"] for i in items if i["present"]]
    return {
        "doshas": items,
        "summary": {
            "present": present,
            "count": len(present),
            "note": "Doshas are classical indicators of tendencies. Many are reduced by cancellations "
                    "or by the strength of the rest of the chart; they are not predictions of misfortune.",
        },
    }


def nakshatra_list() -> list[str]:
    return NAKSHATRAS
