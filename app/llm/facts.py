"""Calculated facts added to a chat prompt when the question needs them.

The chat model is a reasoning layer, not a calculator. Left alone it gets classical rules wrong (it once said Mars in
the 1st house gives no Manglik dosha) and invents mantras. For the topics below the engine's own results are put in the
prompt, so the answer quotes the calculation instead of guessing. Only the topics a question touches are added, which
keeps the prompt small: a question about career adds nothing.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.astrology import dasha as D
from app.astrology import doshas as DO
from app.astrology import remedies as R

MAX_FACT_CHARS = 1500          # hard cap for everything added (about 400 tokens)

_DOSHA = re.compile(
    r"\b(dosh\w*|manglik|mangal\w*|kuja|kuj|kaal\s?sarp\w*|kalsarp\w*|sade\s?sati|sadesati|saade\s?saati|pitru|pitra|"
    r"grahan|guru\s?chandal\w*|angarak|shrapit|vish\s?dosh\w*|gand\s?mool\w*|mool\s?dosh\w*|cursed?|afflict\w*)\b", re.I)
_MARRIAGE = re.compile(r"\b(marri\w*|spouse|wedding|husband|wife|partner|relationship|love|kundli\s?milan|match\w*|"
                       r"girlfriend|boyfriend|shaadi|vivah)\b", re.I)
_REMEDY = re.compile(r"\b(remed\w*|upay\w*|upaya|mantra\w*|gemstone\w*|gem|stone\w*|puja\w*|pooja|donat\w*|charity|"
                     r"fast\w*|vrat|rudraksha|solution|what\s+(should|can)\s+i\s+do|how\s+(to|can)\s+i\s+(fix|improve|reduce))\b", re.I)
_TIMING = re.compile(r"\b(when|timing|time\s?line|dasha|mahadasha|antardasha|period|next|soon|upcoming|this\s+year|"
                     r"next\s+year|how\s+long|years?|months?)\b", re.I)


def _dosha_lines(chart, now: datetime, only: tuple[str, ...] | None = None) -> tuple[list[str], list[str]]:
    result = DO.analyze(chart, now)
    items = [d for d in result["doshas"] if only is None or d["name"] in only]
    lines, keys = [], []
    for d in items:
        if not d["present"]:
            continue
        cancel = f"; reduced because: {'; '.join(d['cancellations'][:2])}" if d["cancellations"] else ""
        lines.append(f"- {d['name']}: PRESENT, {d['severity']}. {d['reason']}{cancel}")
        keys.append(d["remedy_key"])
    absent = [d["name"] for d in items if not d["present"]]
    if absent and only is None:
        lines.append("- Not present: " + ", ".join(absent))
    elif absent and only:
        lines.append("- " + ", ".join(absent) + ": NOT present")
    return lines, keys


def _timing_lines(chart, now: datetime) -> list[str]:
    timeline = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    naive = now.replace(tzinfo=None)
    upcoming = []
    for maha in timeline:
        for a in maha["antardashas"]:
            if a["start"] > naive:
                upcoming.append(f"{maha['lord']}-{a['lord']} from {a['start']:%b %Y} to {a['end']:%b %Y}")
            if len(upcoming) == 3:
                break
        if len(upcoming) == 3:
            break
    return ["Next dasha sub-periods: " + "; ".join(upcoming)] if upcoming else []


def _remedy_lines(chart, now: datetime, dosha_keys: list[str]) -> list[str]:
    lines: list[str] = []
    for item in R.personal_remedies(chart, now, max_items=2)["remedies"]:
        gem = ""
        if item.get("gemstone"):
            g = item["gemstone"]
            gem = f"; gemstone {g['name']} ({g.get('day', '')}, only after expert advice)"
        lines.append(
            f"- {item['planet']} ({item['mode']}): {item['why']} Mantra: {item['mantra']['beej']} "
            f"({item['mantra']['japa']}); deity {item['deity']}; fast on {item['fast_day']}; donate "
            f"{', '.join(item['donate']['items'][:3])} on {item['donate']['day']}{gem}")
    for entry in R.dosha_remedies(dosha_keys)[:2]:
        lines.append(f"- For {entry['dosha'].replace('_', ' ')} dosha: " + " ".join(entry["remedies"][:2]))
    return lines


def verified_facts(question: str, chart, now: datetime | None = None) -> str:
    """Text for the prompt's calculated-facts block, or '' when the question needs none."""
    if chart is None or not question:
        return ""
    now = now or datetime.now(timezone.utc)
    sections: list[str] = []
    dosha_keys: list[str] = []
    try:
        if _DOSHA.search(question):
            lines, dosha_keys = _dosha_lines(chart, now)
            sections.append("Doshas calculated from this chart:\n" + "\n".join(lines))
        elif _MARRIAGE.search(question):
            lines, dosha_keys = _dosha_lines(chart, now, only=("Manglik (Kuja) Dosha",))
            sections.append("Manglik check for marriage:\n" + "\n".join(lines))
            if dosha_keys:        # a dosha that is present comes with its classical remedy, so none is invented
                sections.append("Classical remedy for it: " + " ".join(R.dosha_remedies(dosha_keys)[0]["remedies"][:2]))
        if _TIMING.search(question):
            lines = _timing_lines(chart, now)
            if lines:
                sections.append("\n".join(lines))
        if _REMEDY.search(question):
            lines = _remedy_lines(chart, now, dosha_keys)
            if lines:
                sections.append("Remedies chosen by the rule engine for this chart (mention only these):\n" + "\n".join(lines))
    except Exception:
        return ""              # a facts failure must never break the chat; the plain prompt still works
    text = "\n\n".join(sections)
    return text if len(text) <= MAX_FACT_CHARS else text[:MAX_FACT_CHARS].rsplit("\n", 1)[0]
