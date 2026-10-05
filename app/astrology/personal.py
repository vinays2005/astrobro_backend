"""Personalised horoscope: sign-based Gochar plus Chandra Bala, Tara Bala, running Dasha and Sade Sati."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.astrology import dasha as D
from app.astrology import horoscope as H
from app.astrology import transits as T
from app.astrology.constants import NAKSHATRAS, SIGNS

TARA_NAMES = ["Janma", "Sampat", "Vipat", "Kshema", "Pratyari", "Sadhaka", "Naidhana", "Mitra", "Parama Mitra"]
_TARA_MEANING = {
    "Janma": "Neutral; stay grounded and avoid starting major ventures.",
    "Sampat": "Prosperity; good for gains and new efforts.",
    "Vipat": "Danger; obstacles and setbacks are likelier, so be careful.",
    "Kshema": "Wellbeing; a safe and comfortable star for the day.",
    "Pratyari": "Obstruction; opposition or delays may arise.",
    "Sadhaka": "Achievement; good for accomplishing tasks.",
    "Naidhana": "Vadha; the weakest star, so avoid risk and conflict.",
    "Mitra": "Friendliness; supportive people and easy cooperation.",
    "Parama Mitra": "Great friendliness; very favourable for cooperation and help.",
}
_BAD_TARAS = {3, 5, 7}
_GOOD_CHANDRA = {1, 3, 6, 7, 10, 11}


def chandra_bala(natal_moon_sign: int, transit_moon_sign: int) -> dict:
    house = T.house_from(transit_moon_sign, natal_moon_sign)
    good = house in _GOOD_CHANDRA
    return {"house_from_natal_moon": house, "good": good,
            "text": "Chandra Bala is strong: the Moon supports your mind and plans today." if good
            else "Chandra Bala is weak: the Moon is in a less supportive position, so take extra care."}


def tara_bala(natal_nak: int, transit_nak: int) -> dict:
    count = ((transit_nak - natal_nak) % 27) + 1
    n = (count % 9) or 9
    return {"tara": TARA_NAMES[n - 1], "number": n, "good": n not in _BAD_TARAS,
            "text": _TARA_MEANING[TARA_NAMES[n - 1]],
            "today_nakshatra": NAKSHATRAS[transit_nak]}


def _clip(v: float) -> int:
    return int(max(5, min(98, round(v))))


def _dasha_block(chart, when: datetime) -> dict | None:
    timeline = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    cur = D.period_at(timeline, when.replace(tzinfo=None))
    if not cur:
        return None
    asc = chart.ascendant["sign_index"]
    out = {}
    for key, level in (("maha", "mahadasha"), ("antar", "antardasha"), ("praty", "pratyantardasha")):
        p = cur.get(key)
        if not p:
            continue
        profile = D.lord_profile(p["lord"], chart.planets, chart.houses, asc)
        out[level] = {"lord": p["lord"], "start": p["start"].date().isoformat(), "end": p["end"].date().isoformat(),
                      "interpretation": D.interpret(p["lord"], profile, level)}
    return out


def _sade_sati_block(chart, when: datetime) -> dict:
    moon_sign = int(chart.planets["Moon"].longitude / 30) % 12
    tl = T.sade_sati_timeline(moon_sign, when, span_years=3)
    cur = tl["current"]
    return {"active": bool(cur and cur["type"] == "sade_sati"), "current": cur}


def personal_forecast(chart, period: str, on: date | None, tz: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sign_idx = int(chart.planets["Moon"].longitude / 30) % 12
    today = now.astimezone(H.E.tzinfo(tz)).date()
    on = on or today
    base = H.forecast(SIGNS[sign_idx], period, on, tz, today=today)

    natal = {"moon_sign": SIGNS[sign_idx], "nakshatra": chart.nakshatra_moon.name,
             "pada": chart.nakshatra_moon.pada, "lagna": chart.ascendant["sign"]}
    when = datetime.combine(
        today + timedelta(days=1) if period == "tomorrow" else (on if period != "today" else today),
        datetime.min.time(), tzinfo=timezone.utc,
    )
    personal: dict = {"natal": natal, "dasha": _dasha_block(chart, when), "sade_sati": _sade_sati_block(chart, when)}

    if base["period"] == "daily":
        day = date.fromisoformat(base["date"])
        pos = H._positions_for(day.isoformat(), tz)["pos"]
        cb = chandra_bala(sign_idx, pos["Moon"]["sign_index"])
        tb = tara_bala(chart.nakshatra_moon.index, pos["Moon"]["nakshatra_index"])
        adj = (3 if cb["good"] else -3) + (3 if tb["good"] else -3)
        scores = {k: _clip(v + (adj if k == "overall" else adj / 2)) for k, v in base["scores"].items()}
        personal.update({"chandra_bala": cb, "tara_bala": tb, "adjusted_scores": scores,
                         "adjusted_mood": H.mood_for(scores["overall"])})
        extra = []
        if personal["dasha"] and personal["dasha"].get("antardasha"):
            ad = personal["dasha"]["antardasha"]
            extra.append(f"You are running {personal['dasha']['mahadasha']['lord']} Mahadasha and {ad['lord']} Antardasha.")
        if personal["sade_sati"]["active"]:
            extra.append(f"Sade Sati is active ({personal['sade_sati']['current']['phase']}), so steady patience pays off.")
        extra.append(f"Tara Bala is {tb['tara']} ({'favourable' if tb['good'] else 'unfavourable'}) and Chandra Bala is "
                     f"{'strong' if cb['good'] else 'weak'}.")
        personal["summary"] = " ".join([base["summary"], *extra])
    else:
        notes = []
        if personal["dasha"] and personal["dasha"].get("antardasha"):
            ad = personal["dasha"]["antardasha"]
            notes.append(f"Running {personal['dasha']['mahadasha']['lord']} Mahadasha with {ad['lord']} Antardasha until {ad['end']}.")
        if personal["sade_sati"]["active"]:
            notes.append(f"Sade Sati is active ({personal['sade_sati']['current']['phase']}).")
        personal["summary"] = " ".join([base["summary"], *notes])

    base["personal"] = personal
    return base
