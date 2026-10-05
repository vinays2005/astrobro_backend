"""Regression tests for Panchang bugs: fake sunrise, wrong Choghadiya/Hora tables, lunar month, Hindu year."""
from __future__ import annotations

from datetime import date

import pytest

from app.astrology import calendar_hindu as CH
from app.astrology.constants import NAKSHATRAS
from app.astrology.panchang import (
    _HORA_PLANET_ORDER,
    _HORA_START_INDEX,
    _NAKSHATRA_GANAS,
    PanchangEngine,
    choghadiya_names,
)

_STD_DAY = {
    0: "Udveg Char Labh Amrit Kaal Shubh Rog Udveg", 1: "Amrit Kaal Shubh Rog Udveg Char Labh Amrit",
    2: "Rog Udveg Char Labh Amrit Kaal Shubh Rog", 3: "Labh Amrit Kaal Shubh Rog Udveg Char Labh",
    4: "Shubh Rog Udveg Char Labh Amrit Kaal Shubh", 5: "Char Labh Amrit Kaal Shubh Rog Udveg Char",
    6: "Kaal Shubh Rog Udveg Char Labh Amrit Kaal",
}
_STD_NIGHT = {
    0: "Shubh Amrit Char Rog Kaal Labh Udveg Shubh", 1: "Char Rog Kaal Labh Udveg Shubh Amrit Char",
    2: "Kaal Labh Udveg Shubh Amrit Char Rog Kaal", 3: "Udveg Shubh Amrit Char Rog Kaal Labh Udveg",
    4: "Amrit Char Rog Kaal Labh Udveg Shubh Amrit", 5: "Rog Kaal Labh Udveg Shubh Amrit Char Rog",
    6: "Labh Udveg Shubh Amrit Char Rog Kaal Labh",
}


class TestSunriseAndSunset:
    @pytest.mark.parametrize("name,lat,lon,sunrise,sunset", [
        ("Delhi", 28.6139, 77.2090, "06:15", "18:02"),
        ("Mumbai", 19.0760, 72.8777, "06:29", "18:23"),
    ])
    def test_real_sunrise_not_the_06_18_fallback(self, name, lat, lon, sunrise, sunset):
        p = PanchangEngine().calculate(date(2026, 10, 5), lat, lon, "Asia/Kolkata")
        assert (p.sun_moon.sunrise, p.sun_moon.sunset) == (sunrise, sunset)
        assert p.sun_moon.moonrise != "--:--" and p.sun_moon.moonset != "--:--"

    def test_cities_differ(self):
        e = PanchangEngine()
        a = e.calculate(date(2026, 10, 5), 28.6139, 77.2090, "Asia/Kolkata")
        b = e.calculate(date(2026, 10, 5), 13.0827, 80.2707, "Asia/Kolkata")
        assert a.sun_moon.sunrise != b.sun_moon.sunrise

    def test_rahu_kaal_for_monday_is_second_eighth(self):
        p = PanchangEngine().calculate(date(2026, 10, 5), 28.6139, 77.2090, "Asia/Kolkata")  # a Monday
        assert p.vara == "Monday" and p.rahu_kaal == "07:44 – 09:12"


class TestChoghadiyaAndHora:
    @pytest.mark.parametrize("vara", range(7))
    def test_day_and_night_tables_match_standard(self, vara):
        assert " ".join(choghadiya_names(vara)) == _STD_DAY[vara]
        assert " ".join(choghadiya_names(vara, night=True)) == _STD_NIGHT[vara]

    def test_first_hora_is_the_weekday_lord(self):
        lords = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
        assert [_HORA_PLANET_ORDER[_HORA_START_INDEX[v]] for v in range(7)] == lords


class TestGana:
    def test_panchang_uses_corrected_gana_table(self):
        assert _NAKSHATRA_GANAS[NAKSHATRAS.index("Magha")] == "Rakshasa"
        assert _NAKSHATRA_GANAS[NAKSHATRAS.index("Rohini")] == "Manushya"
        assert [_NAKSHATRA_GANAS.count(g) for g in ("Deva", "Manushya", "Rakshasa")] == [9, 9, 9]


class TestLunarCalendar:
    def test_month_names_follow_sankranti_rule(self):
        names = {m.label for m in CH.months_for_year(2026)}
        assert {"Chaitra", "Vaishakha", "Ashwin", "Kartik"} <= names

    def test_2026_has_adhika_jyeshtha(self):
        adhika = [m for m in CH.months_for_year(2026) if m.adhika]
        assert [m.label for m in adhika] == ["Adhika Jyeshtha"]

    def test_2023_adhika_shravana(self):
        assert "Adhika Shravana" in {m.label for m in CH.months_for_year(2023)}

    def test_masa_info_on_known_days(self):
        p = PanchangEngine()
        assert p.calculate(date(2026, 10, 5), 28.6139, 77.2090, "Asia/Kolkata").masa == "Bhadrapada"   # Pitru Paksha
        assert p.calculate(date(2026, 11, 8), 28.6139, 77.2090, "Asia/Kolkata").masa == "Ashwin"      # Diwali month

    def test_purnimanta_name_differs_for_krishna_paksha(self):
        r = PanchangEngine().calculate(date(2026, 10, 5), 28.6139, 77.2090, "Asia/Kolkata")
        assert r.tithi.paksha == "Krishna" and r.masa_purnimanta == "Ashwin"

    def test_new_year_and_vikram_samvat_flip_on_gudi_padwa(self):
        assert CH.new_year_start(2026) == date(2026, 3, 19)
        assert CH.hindu_year(date(2026, 3, 18))["vikram_samvat"] == 2082
        assert CH.hindu_year(date(2026, 3, 19))["vikram_samvat"] == 2083
        assert CH.hindu_year(date(2026, 3, 19))["shaka_samvat"] == 1948

    def test_ritu_follows_lunar_month(self):
        assert PanchangEngine().calculate(date(2026, 11, 8), 28.6139, 77.2090, "Asia/Kolkata").ritu == "Sharad"
