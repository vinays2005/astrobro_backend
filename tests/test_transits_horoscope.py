"""Transits, Gochar rules, Sade Sati and horoscope generation."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from app.astrology import ephem as E
from app.astrology import horoscope as H
from app.astrology import personal as PS
from app.astrology import transits as T
from app.astrology.constants import SIGNS

IST = "Asia/Kolkata"


def _jd(y, m, d):
    return E.to_jd(datetime(y, m, d, tzinfo=timezone.utc))


def _local_date(jd):
    return E.jd_to_local(jd, IST).date().isoformat()


class TestPublishedPlanetaryDates:
    """Dates published in Vedic calendars (IST); Swiss Ephemeris should reproduce them."""

    def test_saturn_enters_pisces_2025(self):
        ev = E.ingresses("Saturn", _jd(2025, 1, 1), _jd(2025, 12, 31))
        assert [(_local_date(e["jd"]), e["to_sign"]) for e in ev] == [("2025-03-29", "Pisces")]

    def test_jupiter_ingresses_2025_26(self):
        ev = E.ingresses("Jupiter", _jd(2025, 1, 1), _jd(2027, 1, 1))
        got = [(_local_date(e["jd"]), e["to_sign"], e["retrograde"]) for e in ev]
        assert got == [("2025-05-14", "Gemini", False), ("2025-10-18", "Cancer", False),
                       ("2025-12-05", "Gemini", True), ("2026-06-02", "Cancer", False),
                       ("2026-10-31", "Leo", False)]

    def test_makar_sankranti_2026(self):
        ev = E.ingresses("Sun", _jd(2026, 1, 1), _jd(2026, 2, 1))
        assert _local_date(ev[0]["jd"]) == "2026-01-14" and ev[0]["to_sign"] == "Capricorn"

    def test_jupiter_stations(self):
        st = E.stations("Jupiter", _jd(2026, 1, 1), _jd(2027, 1, 1))
        assert [(_local_date(s["jd"]), s["type"]) for s in st] == [("2026-03-11", "direct_start"),
                                                                    ("2026-12-13", "retrograde_start")]

    def test_new_and_full_moon(self):
        assert [_local_date(j) for j in E.lunations(_jd(2026, 11, 1), _jd(2026, 11, 30), 0.0)] == ["2026-11-09"]
        assert [_local_date(j) for j in E.lunations(_jd(2026, 10, 1), _jd(2026, 10, 31), 180.0)] == ["2026-10-26"]

    def test_positions_have_expected_shape(self):
        p = E.positions(_jd(2026, 10, 5))
        assert set(p) == set(E.PLANETS)
        assert p["Rahu"]["sign"] == "Aquarius" and p["Ketu"]["sign"] == "Leo"
        assert abs((p["Ketu"]["longitude"] - p["Rahu"]["longitude"]) % 360 - 180) < 1e-6
        assert p["Saturn"]["retrograde"] is True


def _pos(placements: dict[str, int]) -> dict[str, dict]:
    """Synthetic transit positions: {planet: sign_index}; unspecified planets sit in Aries."""
    return {p: {"sign_index": placements.get(p, 0), "sign": SIGNS[placements.get(p, 0)], "retrograde": False}
            for p in E.PLANETS}


class TestGochar:
    def test_favourable_house_tables(self):
        assert T.FAVOURABLE_HOUSES["Saturn"] == {3, 6, 11}
        assert T.FAVOURABLE_HOUSES["Jupiter"] == {2, 5, 7, 9, 11}
        assert 10 in T.FAVOURABLE_HOUSES["Sun"] and 12 not in T.FAVOURABLE_HOUSES["Sun"]

    def test_unfavourable_transit_scores_negative(self):
        g = T.gochar(_pos({"Saturn": 7}), 0)       # Saturn in the 8th from the Moon
        assert g["Saturn"]["favourable"] is False and g["Saturn"]["value"] < 0

    def test_vedha_obstructs_a_favourable_transit(self):
        # Sun in the 3rd (favourable) is obstructed by a planet in the 9th
        g = T.gochar(_pos({"Sun": 2, "Mercury": 8}), 0)
        assert g["Sun"]["favourable"] and g["Sun"]["obstructed_by"] == "Mercury"
        assert 0 < g["Sun"]["value"] < 1

    def test_sun_saturn_do_not_obstruct_each_other(self):
        g = T.gochar(_pos({"Sun": 2, "Saturn": 8}), 0)
        assert g["Sun"]["obstructed_by"] is None and g["Sun"]["value"] == 1.0

    def test_text_mentions_house_and_planet(self):
        g = T.gochar(_pos({"Jupiter": 4}), 0)["Jupiter"]
        assert "Jupiter in your 5th house" in g["text"]

    def test_retrograde_note_added(self):
        assert "retrograde" in T.describe("Mars", 3, True, None, True)


class TestSadeSati:
    NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def test_pisces_moon_is_in_peak_phase(self):
        ss = T.sade_sati_timeline(11, self.NOW)
        assert ss["active"] and "Peak" in ss["current"]["phase"]
        assert (ss["current"]["start"], ss["current"]["end"]) == ("2025-03-29", "2027-06-02")

    def test_aries_moon_is_in_rising_phase_and_taurus_is_free(self):
        assert "Rising" in T.sade_sati_timeline(0, self.NOW)["current"]["phase"]
        assert T.sade_sati_timeline(1, self.NOW)["current"] is None

    def test_dhaiya_for_fourth_from_moon(self):
        # Saturn in Pisces is the 4th from a Gemini Moon (Gemini=2 -> Pisces=11 is 10th); use Virgo=5? Pisces is 7 ahead
        cur = T.sade_sati_timeline((11 - 3) % 12, self.NOW)["current"]
        assert cur and cur["type"] == "dhaiya" and "Kantaka" in cur["phase"]

    def test_periods_are_chronological_and_non_overlapping(self):
        periods = T.sade_sati_timeline(11, self.NOW, span_years=35)["periods"]
        for a, b in zip(periods, periods[1:]):
            assert a["end"] <= b["start"]


class TestEventsFeed:
    def test_upcoming_events_sorted_and_titled(self):
        evs = T.upcoming_events(datetime(2026, 10, 5, tzinfo=timezone.utc), 60)
        assert evs == sorted(evs, key=lambda e: e["jd"])
        titles = [e["title"] for e in evs]
        assert "Jupiter enters Leo" in titles and "Mercury turns retrograde in Libra" in titles

    def test_moon_events_can_be_excluded(self):
        evs = T.upcoming_events(datetime(2026, 10, 5, tzinfo=timezone.utc), 60, ("Jupiter",), moon_events=False)
        assert {e["type"] for e in evs} <= {"ingress", "retrograde_start", "direct_start"}


class TestHoroscope:
    def test_sign_aliases(self):
        assert H.resolve_sign("Mesha") == 0 and H.resolve_sign(" KUMBHA ") == 10 and H.resolve_sign("vrishchika") == 7
        with pytest.raises(ValueError):
            H.resolve_sign("ophiuchus")

    def test_deterministic(self):
        a = H.forecast("Leo", "today", None, IST, today=date(2026, 10, 5))
        b = H.forecast("Leo", "today", None, IST, today=date(2026, 10, 5))
        assert a == b

    def test_daily_shape_and_bounds(self):
        d = H.forecast("Cancer", "daily", date(2026, 10, 5), IST)
        assert set(d["scores"]) == {"overall", "love", "career", "finance", "health", "family"}
        assert all(5 <= v <= 98 for v in d["scores"].values())
        assert d["mood"] in {"Excellent", "Good", "Balanced", "Challenging", "Difficult"}
        assert len(d["influences"]) == 4 and d["influences"][0]["planet"] == "Moon"
        assert d["lucky"]["numbers"] and d["advice"]

    def test_mood_distribution_is_balanced_not_gloomy(self):
        moods = Counter(H.daily(s, date(2026, 6, 1) + timedelta(days=i), IST)["mood"]
                        for s in range(12) for i in range(60))
        n = sum(moods.values())
        assert moods["Balanced"] / n > 0.30
        assert moods["Difficult"] / n < 0.20
        assert moods["Excellent"] / n > 0.02
        assert (moods["Good"] + moods["Excellent"]) / n > 0.12

    def test_signs_get_different_forecasts(self):
        scores = {H.daily(s, date(2026, 10, 5), IST)["scores"]["overall"] for s in range(12)}
        assert len(scores) > 3

    def test_today_and_tomorrow_use_the_right_dates(self):
        t = H.forecast("Leo", "today", None, IST, today=date(2026, 10, 5))
        m = H.forecast("Leo", "tomorrow", None, IST, today=date(2026, 10, 5))
        assert (t["date"], m["date"]) == ("2026-10-05", "2026-10-06")

    def test_weekly_monthly_yearly(self):
        w = H.forecast("Leo", "weekly", date(2026, 10, 5), IST)
        assert len(w["daily"]) == 7 and w["range"] == {"start": "2026-10-05", "end": "2026-10-11"}
        m = H.forecast("Pisces", "monthly", date(2026, 10, 1), IST)
        assert m["range"]["end"] == "2026-10-31" and len(m["weeks"]) == 5
        y = H.forecast("Aries", "yearly", date(2026, 1, 1), IST)
        assert len(y["months"]) == 12 and [i["planet"] for i in y["key_influences"]] == ["Jupiter", "Saturn", "Rahu", "Ketu"]
        assert not any("Moon" in s["title"] for s in y["slow_planet_transits"])

    def test_invalid_period_rejected(self):
        with pytest.raises(ValueError):
            H.forecast("Leo", "decade", None, IST)

    def test_moon_sign_change_reported(self):
        ctx = H._positions_for("2026-10-05", IST)
        d = H.daily(3, date(2026, 10, 5), IST)
        assert d["moon"]["sign"] == ctx["pos"]["Moon"]["sign"]


class TestChandraAndTaraBala:
    def test_chandra_bala_houses(self):
        assert PS.chandra_bala(0, 2)["good"] is True      # 3rd from the natal Moon
        assert PS.chandra_bala(0, 7)["good"] is False     # 8th

    def test_tara_bala_counts(self):
        assert PS.tara_bala(0, 2)["tara"] == "Vipat" and PS.tara_bala(0, 2)["good"] is False     # count 3
        assert PS.tara_bala(0, 1)["tara"] == "Sampat" and PS.tara_bala(0, 1)["good"] is True      # count 2
        assert PS.tara_bala(5, 5)["tara"] == "Janma"

    def test_bad_taras_are_three_five_seven(self):
        bad = {n for n in range(1, 10) if not PS.tara_bala(0, n - 1)["good"]}
        assert bad == {3, 5, 7}
