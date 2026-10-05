"""Upcoming-event feed for push/local notifications: dasha changes, transits, festivals, daily forecast."""
from __future__ import annotations

import zlib
from datetime import date, datetime, timedelta, timezone

from app.astrology import calendar_hindu as CH
from app.astrology import dasha as D
from app.astrology import ephem as E
from app.astrology import personal as PS
from app.astrology import transits as T
from app.astrology.constants import SIGNS

_PRIORITY_VRATAS = {"ekadashi", "pradosh", "purnima", "amavasya", "sankashti", "masik_shivratri"}


def _item(kind: str, when: date, title: str, body: str, priority: str = "normal", link: str = "", time: str | None = None,
          uid: str | None = None) -> dict:
    return {
        "id": uid or f"{kind}:{when.isoformat()}:{zlib.crc32(title.encode()) % 100000}",
        "type": kind, "date": when.isoformat(), "time": time, "title": title, "body": body,
        "priority": priority, "deep_link": link,
    }


def build_feed(chart, name: str, dob: date, start: date, days: int, lat: float, lon: float, tz: str,
               now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    end = start + timedelta(days=days)
    sign_idx = int(chart.planets["Moon"].longitude / 30) % 12
    asc = chart.ascendant["sign_index"]
    items: list[dict] = []

    # 1) Daily forecast teasers
    for i in range(min(days, 14)):
        d = start + timedelta(days=i)
        f = PS.personal_forecast(chart, "daily", d, tz, now)
        pers = f["personal"]
        mood = pers.get("adjusted_mood", f["mood"])
        tara = pers.get("tara_bala", {})
        body = f"{mood} day for {SIGNS[sign_idx]}. " + (
            "Tara and Chandra Bala support you." if tara.get("good") and pers["chandra_bala"]["good"] else
            "Take extra care today." if not tara.get("good") and not pers["chandra_bala"]["good"] else
            f.get("advice", ""))
        items.append(_item("daily_horoscope", d, f"Your horoscope for {d.strftime('%a %d %b')}", body.strip(),
                           link="horoscope/daily", time="07:00", uid=f"daily:{d.isoformat()}"))

    # 2) Dasha period changes
    timeline = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    for maha in timeline:
        for level, periods in (("Mahadasha", [maha]), ("Antardasha", maha["antardashas"])):
            for p in periods:
                sd = p["start"].date()
                if start <= sd <= end and sd > chart.birth_datetime.date():
                    prof = D.lord_profile(p["lord"], chart.planets, chart.houses, asc)
                    items.append(_item(
                        "dasha_change", sd, f"New {level}: {p['lord']}",
                        D.interpret(p["lord"], prof, "mahadasha" if level == "Mahadasha" else "antardasha"),
                        priority="high" if level == "Mahadasha" else "normal", link="dasha",
                        uid=f"dasha:{level}:{p['lord']}:{sd.isoformat()}"))

    # 3) Transit alerts relevant to the natal Moon sign
    for ev in T.upcoming_events(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc), days,
                                ("Saturn", "Jupiter", "Rahu", "Mars", "Venus", "Mercury")):
        d = E.jd_to_local(ev["jd"], tz).date()
        if ev["type"] == "ingress":
            house = T.house_from(ev["to_sign_index"], sign_idx)
            good = house in T.FAVOURABLE_HOUSES.get(ev["planet"], set())
            slow = ev["planet"] in T.SLOW
            items.append(_item(
                "transit", d, ev["title"],
                f"{ev['planet']} moves into your {T._ORD[house]} house ({T._THEME[house]}): "
                + ("generally supportive." if good else "go carefully in these matters."),
                priority="high" if slow else "normal", link="transits",
                uid=f"transit:{ev['planet']}:{ev['to_sign']}:{d.isoformat()}"))
        elif ev["type"] in ("retrograde_start", "direct_start"):
            items.append(_item("retrograde", d, ev["title"],
                               "Retrograde periods favour review and patience over new starts." if ev["type"] == "retrograde_start"
                               else "The planet turns direct; stalled matters can move again.",
                               link="transits", uid=f"station:{ev['planet']}:{d.isoformat()}"))

    # 4) Sade Sati phase changes
    ss = T.sade_sati_timeline(sign_idx, datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc), span_years=2)
    for per in ss["periods"]:
        sd = date.fromisoformat(per["start"])
        if start <= sd <= end:
            items.append(_item("sade_sati", sd, f"{per['type'].replace('_', ' ').title()} begins",
                               f"{per['phase']}. Steady routines, patience and service help.", priority="high",
                               link="dosha", uid=f"ss:{per['phase']}:{sd.isoformat()}"))

    # 5) Festivals and vratas
    events = []
    for y in {start.year, end.year}:
        events += CH.events_for_year(y, lat, lon, tz)
    for e in events:
        d = date.fromisoformat(e["date"])
        if not (start <= d <= end):
            continue
        base = e["key"].split("_")[0]
        major = e["type"] in ("festival", "sankranti")
        if major or base in _PRIORITY_VRATAS:
            items.append(_item("festival" if major else "vrata", d, e["name"], e["note"], priority="high" if major else "normal",
                               link="calendar", uid=f"cal:{e['key']}:{e['date']}"))

    # 6) Birthday
    for yr in {start.year, end.year}:
        try:
            bd = date(yr, dob.month, dob.day)
        except ValueError:
            bd = date(yr, 3, 1)
        if start <= bd <= end:
            items.append(_item("birthday", bd, f"Happy Birthday, {name}!", "Wishing you a blessed year ahead.",
                               priority="high", link="horoscope/yearly", uid=f"bday:{bd.isoformat()}"))

    items.sort(key=lambda i: (i["date"], 0 if i["priority"] == "high" else 1, i["type"]))
    seen, unique = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)
    return {
        "name": name, "range": {"start": start.isoformat(), "end": end.isoformat()},
        "moon_sign": SIGNS[sign_idx], "count": len(unique), "items": unique,
    }
