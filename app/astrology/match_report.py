"""Detailed Kundli Milan report and the Love Calculator. Deterministic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.astrology import dasha as D
from app.astrology import doshas as DO
from app.astrology import matching as M
from app.astrology import remedies as R
from app.astrology import strength as S
from app.astrology.constants import NATURAL_ENEMIES, NATURAL_FRIENDS, SIGNS

_D9_START = {0: 0, 1: 9, 2: 6, 3: 3, 4: 0, 5: 9, 6: 6, 7: 3, 8: 0, 9: 9, 10: 6, 11: 3}


def _label(score: float) -> str:
    return "excellent" if score >= 75 else "good" if score >= 60 else "moderate" if score >= 45 else "needs care"


def moon_placement(chart) -> M.MoonPlacement:
    return M.MoonPlacement(chart.planets["Moon"].longitude)


def navamsa_lagna(chart) -> int:
    lon = chart.ascendant["longitude"]
    return (_D9_START[int(lon / 30) % 12] + int((lon % 30) * 9 / 30)) % 12


# ── Manglik compatibility ─────────────────────────────────────────────────────

def _manglik_effective(m: dict) -> str:
    """'strong' | 'mild' | 'none' after cancellations."""
    if not m["present"]:
        return "none"
    if m["cancellations"] or m["severity"] == "low":
        return "mild"
    return "strong"


def manglik_compatibility(boy: dict, girl: dict) -> dict:
    b, g = _manglik_effective(boy), _manglik_effective(girl)
    if b == "strong" and g == "strong":
        verdict, ok = "Both partners are Manglik, so the dosha is mutually balanced.", True
    elif b == "none" and g == "none":
        verdict, ok = "Neither partner has an effective Manglik Dosha.", True
    elif "strong" in (b, g) and "none" in (b, g):
        who = "groom" if b == "strong" else "bride"
        verdict, ok = f"Only the {who} has an effective Manglik Dosha; this is a mismatch that classical texts advise remedying.", False
    else:
        verdict, ok = "Any Manglik influence is mild or cancelled on at least one side, so it is of limited concern.", True
    return {"boy": b, "girl": g, "balanced": ok, "verdict": verdict}


# ── Marriage timing (dasha based) ─────────────────────────────────────────────

def marriage_windows(chart, gender: str | None, now: datetime, years: int = 12) -> list[dict]:
    seventh = chart.houses[6].lord
    second, eleventh = chart.houses[1].lord, chart.houses[10].lord
    karakas = {"male": {"Venus"}, "female": {"Jupiter"}}.get(gender or "", {"Venus", "Jupiter"})
    primary = {seventh, *karakas, *chart.houses[6].occupants}
    supporting = {second, eleventh, "Venus"}
    timeline = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    start = now.replace(tzinfo=None)
    end = start + timedelta(days=365.25 * years)
    out = []
    for maha in timeline:
        if maha["end"] < start or maha["start"] > end:
            continue
        for antar in maha["antardashas"]:
            if antar["end"] < start or antar["start"] > end:
                continue
            pts = (2 * (maha["lord"] in primary) + 2 * (antar["lord"] in primary)
                   + (maha["lord"] in supporting) + (antar["lord"] in supporting))
            if pts >= 3:
                out.append({
                    "period": f"{maha['lord']} / {antar['lord']}",
                    "start": max(antar["start"], start).date().isoformat(),
                    "end": min(antar["end"], end).date().isoformat(),
                    "strength": "strong" if pts >= 4 else "supportive",
                    "reason": f"{maha['lord']} and {antar['lord']} are linked with the 7th house, marriage karaka or family and gains houses.",
                })
    return out[:8]


# ── Single-person marriage profile ────────────────────────────────────────────

def person_profile(chart, gender: str | None, now: datetime) -> dict:
    seventh = S.house_strength(chart, 7)
    venus, jupiter = S.planet_strength(chart, "Venus"), S.planet_strength(chart, "Jupiter")
    d9_lagna = navamsa_lagna(chart)
    d9_seventh_sign = (d9_lagna + 6) % 12
    d9_seventh_lord = M.SIGN_LORDS[d9_seventh_sign]
    d9 = chart.navamsha
    marriage_score = round(0.45 * seventh["score"] + 0.3 * venus["score"] + 0.25 * jupiter["score"])
    manglik = DO.manglik(chart)
    return {
        "lagna": chart.ascendant["sign"], "moon_sign": chart.planets["Moon"].sign,
        "nakshatra": chart.nakshatra_moon.name, "pada": chart.nakshatra_moon.pada,
        "seventh_house": seventh, "venus": venus, "jupiter": jupiter,
        "navamsa": {
            "lagna": SIGNS[d9_lagna],
            "venus_dignity": d9["Venus"].dignity if "Venus" in d9 else None,
            "jupiter_dignity": d9["Jupiter"].dignity if "Jupiter" in d9 else None,
            "seventh_lord": d9_seventh_lord,
            "seventh_lord_dignity": d9[d9_seventh_lord].dignity if d9_seventh_lord in d9 else None,
        },
        "marriage_score": marriage_score, "marriage_label": _label(marriage_score),
        "manglik": manglik,
        "marriage_windows": marriage_windows(chart, gender, now),
    }


# ── Couple-level areas ────────────────────────────────────────────────────────

def _avg(*xs: float) -> int:
    return int(round(sum(xs) / len(xs)))


def couple_areas(boy, girl, guna: dict) -> dict:
    b = guna["breakdown"]
    both = lambda f: [f(boy), f(girl)]  # noqa: E731
    mercury = both(lambda c: S.planet_strength(c, "Mercury")["score"])
    areas = {
        "emotional": (round((b["graha_maitri"]["score"] / 5 * 0.4 + b["bhakut"]["score"] / 7 * 0.3 + b["gana"]["score"] / 6 * 0.3) * 100),
                      "Emotional understanding: Moon-sign lords, emotional bond and temperament."),
        "physical": (round((b["yoni"]["score"] / 4 * 0.6 + b["vashya"]["score"] / 2 * 0.4) * 100),
                     "Physical and intimate harmony: Yoni and mutual attraction."),
        "communication": (_avg(b["graha_maitri"]["score"] / 5 * 100, *mercury),
                          "Communication: Moon-sign lord friendship and the strength of Mercury in both charts."),
        "finances": (_avg(*both(lambda c: S.house_strength(c, 2)["score"]), *both(lambda c: S.house_strength(c, 11)["score"])),
                     "Shared finances: strength of the 2nd and 11th houses in both charts."),
        "family_life": (_avg(*both(lambda c: S.house_strength(c, 4)["score"]), *both(lambda c: S.house_strength(c, 2)["score"])),
                        "Home and family: the 4th and 2nd houses in both charts."),
        "children": (_avg(*both(lambda c: S.house_strength(c, 5)["score"]), *both(lambda c: S.planet_strength(c, "Jupiter")["score"]),
                          b["nadi"]["score"] / 8 * 100),
                     "Children: the 5th house, Jupiter, and Nadi compatibility."),
        "health_and_longevity_of_union": (round((b["nadi"]["score"] / 8 * 0.5 + b["tara"]["score"] / 3 * 0.5) * 100),
                                          "Wellbeing together: Nadi and Tara koota."),
    }
    return {k: {"score": s, "label": _label(s), "note": n} for k, (s, n) in areas.items()}


# ── Verdict ───────────────────────────────────────────────────────────────────

def verdict(total: float, doshas: dict, manglik: dict, rajju: dict) -> dict:
    critical = []
    for key, label in (("nadi", "Nadi Dosha"), ("bhakoot", "Bhakoot Dosha"), ("gana", "Gana Dosha")):
        d = doshas[key]
        if d["present"] and not d["cancelled"]:
            critical.append(label)
    if not manglik["balanced"]:
        critical.append("Manglik mismatch")
    if rajju["present"]:
        critical.append("Rajju Dosha")

    if total >= 25 and not critical:
        level, text = "Highly recommended", "Strong overall compatibility with no unresolved major dosha."
    elif total >= 18 and len(critical) <= 1:
        level, text = ("Recommended", "Good compatibility.") if not critical else \
            ("Recommended with remedies", f"Good compatibility, but address: {', '.join(critical)}.")
    elif total >= 18:
        level, text = "Acceptable with caution", f"The score is acceptable, but several concerns remain: {', '.join(critical)}."
    else:
        level, text = ("Not recommended on Guna Milan alone",
                       "The Guna Milan score is below the traditional minimum of 18; seek a detailed consultation before deciding.")
    return {"level": level, "summary": text, "concerns": critical,
            "note": "Compatibility analysis is guidance, not a decision. Personal values, understanding and consent matter most."}


def dosha_remedy_keys(doshas: dict, manglik: dict, rajju: dict) -> list[str]:
    keys = [k for k in ("nadi", "bhakoot") if doshas[k]["present"] and not doshas[k]["cancelled"]]
    if not manglik["balanced"]:
        keys.append("manglik")
    return keys


def full_report(boy_chart, girl_chart, boy_name: str, girl_name: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    bm, gm = moon_placement(boy_chart), moon_placement(girl_chart)
    guna = M.ashtakoota(bm, gm)
    extras = M.additional_checks(bm, gm)
    boy_profile = person_profile(boy_chart, "male", now)
    girl_profile = person_profile(girl_chart, "female", now)
    mc = manglik_compatibility(boy_profile["manglik"], girl_profile["manglik"])
    v = verdict(guna["total_score"], guna["doshas"], mc, extras["rajju"])
    remedy_keys = dosha_remedy_keys(guna["doshas"], mc, extras["rajju"])
    return {
        "boy": {"name": boy_name, **{k: boy_profile[k] for k in ("lagna", "moon_sign", "nakshatra", "pada")}},
        "girl": {"name": girl_name, **{k: girl_profile[k] for k in ("lagna", "moon_sign", "nakshatra", "pada")}},
        "guna_milan": guna,
        "doshas": {**guna["doshas"], "rajju": extras["rajju"], "vedha": extras["vedha"]},
        "south_indian_checks": {"mahendra": extras["mahendra"], "stree_dheerga": extras["stree_dheerga"]},
        "manglik": {"boy": boy_profile["manglik"], "girl": girl_profile["manglik"], "compatibility": mc},
        "marriage_profiles": {"boy": _public(boy_profile), "girl": _public(girl_profile)},
        "areas": couple_areas(boy_chart, girl_chart, guna),
        "verdict": v,
        "remedies": R.dosha_remedies(remedy_keys),
        "disclaimer": R.DISCLAIMER,
    }


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in ("manglik", "lagna", "moon_sign", "nakshatra", "pada")}


# ── Love calculator ───────────────────────────────────────────────────────────

_FLAMES = ["Friends", "Lovers", "Affectionate", "Marriage", "Enemies", "Siblings"]
_FLAMES_TEXT = {
    "Friends": "A warm friendship with easy trust.", "Lovers": "Strong romantic spark.",
    "Affectionate": "Tender, caring bond.", "Marriage": "Signs of lasting commitment.",
    "Enemies": "Clashing energies; patience is needed.", "Siblings": "A protective, family-like bond.",
}


def _letters(name: str) -> list[str]:
    return [c for c in name.lower() if c.isalpha()]


def flames(a: str, b: str) -> str:
    la, lb = _letters(a), _letters(b)
    for c in list(la):
        if c in lb:
            la.remove(c)
            lb.remove(c)
    n = len(la) + len(lb)
    if n == 0:
        return "Marriage"
    pool = list(_FLAMES)
    i = 0
    while len(pool) > 1:
        i = (i + n - 1) % len(pool)
        pool.pop(i)
    return pool[0]


def name_score(a: str, b: str) -> int:
    """Classic 'true love' letter-count algorithm (entertainment)."""
    text = f"{a} loves {b}".lower()
    counts = [text.count(c) for c in "loves"]
    nums = counts
    while len(nums) > 2:
        nums = [nums[i] + nums[i + 1] for i in range(len(nums) - 1)]
        nums = [int(d) for n in nums for d in str(n)]
    return int("".join(map(str, nums))) if len(nums) == 2 else 50


def love_calculation(name_a: str, name_b: str, moon_a: M.MoonPlacement | None = None,
                     moon_b: M.MoonPlacement | None = None) -> dict:
    fun = max(30, min(99, name_score(name_a, name_b)))
    kind = flames(name_a, name_b)
    out = {
        "names": [name_a, name_b], "name_score": fun,
        "flames": {"result": kind, "meaning": _FLAMES_TEXT[kind]},
        "note": "The name-based score and FLAMES are for entertainment.",
    }
    if moon_a and moon_b:
        g = M.ashtakoota(moon_a, moon_b)
        astro = round(g["total_score"] / 36 * 100)
        b = g["breakdown"]
        out["astrological"] = {
            "guna_milan": g["total_score"], "percentage": astro, "compatibility": g["compatibility"],
            "emotional": round(b["graha_maitri"]["score"] / 5 * 100),
            "attraction": round((b["yoni"]["score"] / 4 + b["vashya"]["score"] / 2) / 2 * 100),
            "temperament": round(b["gana"]["score"] / 6 * 100),
            "long_term": round((b["nadi"]["score"] / 8 + b["bhakut"]["score"] / 7) / 2 * 100),
        }
        out["love_percentage"] = round(0.7 * astro + 0.3 * fun)
    else:
        out["love_percentage"] = fun
    return out
