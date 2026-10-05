"""Hindu calendar (festivals, vratas) and the Muhurat finder."""
from __future__ import annotations

from datetime import date

import pytest

from app.astrology import calendar_hindu as CH
from app.astrology import muhurat as M

IST = "Asia/Kolkata"
DELHI = (28.6139, 77.2090)

# Dates published by Drik Panchang and other mainstream calendars (Delhi, 2026)
PUBLISHED_2026 = {
    "vasant_panchami": "2026-01-23", "maha_shivratri": "2026-02-15", "holika_dahan": "2026-03-03", "holi": "2026-03-04",
    "ugadi": "2026-03-19", "ram_navami": "2026-03-26", "hanuman_jayanti": "2026-04-02", "akshaya_tritiya": "2026-04-19",
    "buddha_purnima": "2026-05-01", "rath_yatra": "2026-07-16", "guru_purnima": "2026-07-29",
    "raksha_bandhan": "2026-08-28", "janmashtami": "2026-09-04", "ganesh_chaturthi": "2026-09-14",
    "navratri_start": "2026-10-11", "dussehra": "2026-10-20", "karwa_chauth": "2026-10-29", "dhanteras": "2026-11-06",
    "diwali": "2026-11-08", "govardhan_puja": "2026-11-10", "bhai_dooj": "2026-11-11", "kartik_purnima": "2026-11-24",
}


@pytest.fixture(scope="module")
def events_2026():
    return CH.events_for_year(2026, *DELHI, IST)


class TestFestivals2026:
    def test_all_published_dates_match(self, events_2026):
        got = {e["key"]: e["date"] for e in events_2026 if e["type"] == "festival"}
        wrong = {k: (got.get(k), v) for k, v in PUBLISHED_2026.items() if got.get(k) != v}
        assert not wrong, wrong

    def test_dev_uthani_ekadashi_listed_once(self, events_2026):
        on_day = [e for e in events_2026 if e["date"] == "2026-11-20" and "Ekadashi" in e["name"]]
        assert len(on_day) == 1 and "Dev Uthani" in on_day[0]["name"]

    def test_sankrantis(self, events_2026):
        sank = {e["name"]: e["date"] for e in events_2026 if e["type"] == "sankranti"}
        assert sank["Makar Sankranti (Pongal / Uttarayan)"] == "2026-01-14"
        assert sank["Mesha Sankranti (Baisakhi / Vishu / Puthandu)"] == "2026-04-14"
        assert len([e for e in events_2026 if e["type"] == "sankranti"]) == 12

    def test_ekadashi_count_is_about_twenty_four_to_twenty_six(self, events_2026):
        n = len([e for e in events_2026 if e["key"].startswith("ekadashi")])
        assert 22 <= n <= 28

    def test_events_sorted_unique_and_in_year(self, events_2026):
        dates = [e["date"] for e in events_2026]
        assert dates == sorted(dates) and all(d.startswith("2026") for d in dates)
        keys = [(e["key"], e["date"]) for e in events_2026]
        assert len(keys) == len(set(keys))

    def test_event_shape(self, events_2026):
        e = next(x for x in events_2026 if x["key"] == "diwali")
        assert e["tithi"] == "Krishna Amavasya" and e["weekday"] == "Sunday" and e["masa"] == "Ashwin"

    def test_result_is_cached_and_not_shared(self):
        a = CH.events_for_year(2026, *DELHI, IST)
        a.append({"junk": True})
        assert not any("junk" in e for e in CH.events_for_year(2026, *DELHI, IST))


class TestFestivalsOtherYears:
    @pytest.mark.parametrize("year,key,expected", [
        (2025, "maha_shivratri", "2025-02-26"), (2025, "ugadi", "2025-03-30"), (2025, "holi", "2025-03-14"),
        (2025, "ram_navami", "2025-04-06"), (2025, "raksha_bandhan", "2025-08-09"), (2025, "ganesh_chaturthi", "2025-08-27"),
        (2025, "dussehra", "2025-10-02"), (2025, "karwa_chauth", "2025-10-10"), (2025, "diwali", "2025-10-20"),
        (2024, "holi", "2024-03-25"), (2024, "diwali", "2024-10-31"), (2024, "ganesh_chaturthi", "2024-09-07"),
        (2023, "diwali", "2023-11-12"), (2023, "maha_shivratri", "2023-02-18"), (2023, "dussehra", "2023-10-24"),
    ])
    def test_published_dates(self, year, key, expected):
        got = {e["key"]: e["date"] for e in CH.events_for_year(year, *DELHI, IST) if e["type"] == "festival"}
        assert got.get(key) == expected


class TestTithiMachinery:
    def test_kshaya_tithi_goes_to_the_day_it_covers_most(self):
        # Chaturthi on 9-10 Oct 2025 starts at night and runs through the next day: Karwa Chauth is the 10th
        got = {e["key"]: e["date"] for e in CH.events_for_year(2025, *DELHI, IST)}
        assert got["karwa_chauth"] == "2025-10-10"

    def test_tithi_labels(self):
        assert CH.tithi_label(15) == ("Shukla", "Purnima") and CH.tithi_label(30) == ("Krishna", "Amavasya")
        assert CH.tithi_label(1) == ("Shukla", "Pratipada") and CH.tithi_label(26) == ("Krishna", "Ekadashi")

    def test_find_tithi_day_stays_inside_the_lunar_month(self):
        month = next(m for m in CH.months_for_year(2026) if m.label == "Ashwin")
        d = CH.find_tithi_day(month, 30, "pradosh", *DELHI, IST)   # Diwali amavasya, not the previous month's
        assert d == date(2026, 11, 8)

    def test_observe_points_windows(self):
        assert len(CH.observe_points(date(2026, 10, 5), "aparahna", *DELHI, IST)) == 3
        assert len(CH.observe_points(date(2026, 10, 5), "sunrise", *DELHI, IST)) == 1
        with pytest.raises(ValueError):
            CH.observe_points(date(2026, 10, 5), "teatime", *DELHI, IST)


class TestMuhurat:
    def test_marriage_respects_chaturmas_kharmas_and_weekdays(self):
        r = M.find("marriage", date(2026, 10, 5), date(2027, 2, 28), *DELHI, IST)
        dates = r["all_suitable_dates"]
        assert dates, "expected some marriage muhurats"
        assert all(d >= "2026-11-20" for d in dates)                                  # after Dev Uthani Ekadashi
        assert not [d for d in dates if "2026-12-16" <= d <= "2027-01-14"]            # Kharmas
        assert {x["weekday"] for x in r["best_days"]} <= {"Monday", "Wednesday", "Thursday", "Friday"}

    def test_windows_avoid_rahu_kaal(self):
        r = M.find("marriage", date(2026, 11, 21), date(2027, 1, 15), *DELHI, IST, limit=3)
        for day in r["best_days"]:
            rahu = day["avoid"]["rahu_kaal"].split("-")
            for w in day["windows"]:
                assert w["end"] <= rahu[0] or w["start"] >= rahu[1], (day["date"], w, rahu)

    def test_relaxed_mode_is_a_superset_that_still_avoids_banned_periods(self):
        strict = M.find("marriage", date(2026, 10, 5), date(2027, 2, 28), *DELHI, IST)
        relaxed = M.find("marriage", date(2026, 10, 5), date(2027, 2, 28), *DELHI, IST, relaxed=True)
        assert set(strict["all_suitable_dates"]) <= set(relaxed["all_suitable_dates"])
        assert relaxed["suitable_days"] > strict["suitable_days"]
        assert all(d >= "2026-11-20" and not ("2026-12-16" <= d <= "2027-01-14") for d in relaxed["all_suitable_dates"])
        assert relaxed["mode"] == "relaxed" and strict["mode"] == "strict"

    def test_dussehra_is_a_self_auspicious_day_for_a_vehicle(self):
        r = M.find("vehicle_purchase", date(2026, 10, 12), date(2026, 10, 25), *DELHI, IST)
        day = next(d for d in r["best_days"] if d["date"] == "2026-10-20")
        assert any("Abujh" in h for h in day["highlights"]) and day["score"] >= 88

    def test_pitru_paksha_blocks_new_purchases(self):
        r = M.find("vehicle_purchase", date(2026, 9, 28), date(2026, 10, 10), *DELHI, IST, include_excluded=True)
        assert r["suitable_days"] == 0
        assert any("Pitru Paksha" in reason for e in r["excluded_days"] for reason in e["reasons"])

    def test_ravi_pushya_overrides_the_weekday_rule(self):
        r = M.find("property_purchase", date(2026, 10, 25), date(2026, 11, 10), *DELHI, IST)
        day = next(d for d in r["best_days"] if d["date"] == "2026-11-01")     # a Sunday with the Moon in Pushya
        assert day["weekday"] == "Sunday" and "Ravi Pushya Yoga" in day["highlights"]

    def test_puja_is_lenient_and_travel_allows_char(self):
        assert M.RULES["puja"].weekdays == frozenset(range(7))
        assert M.RULES["travel"].allow_char

    def test_errors(self):
        with pytest.raises(ValueError):
            M.find("moon_landing", date(2026, 1, 1), date(2026, 1, 5), *DELHI, IST)
        with pytest.raises(ValueError):
            M.find("marriage", date(2026, 1, 5), date(2026, 1, 1), *DELHI, IST)
        with pytest.raises(ValueError):
            M.find("marriage", date(2026, 1, 1), date(2026, 12, 31), *DELHI, IST)

    def test_event_types_listing(self):
        keys = {e["key"] for e in M.event_types()}
        assert {"marriage", "griha_pravesh", "vehicle_purchase", "property_purchase", "business_launch",
                "naming_ceremony", "mundan", "upanayana", "puja", "travel", "engagement"} <= keys

    def test_location_changes_the_windows(self):
        a = M.find("puja", date(2026, 10, 6), date(2026, 10, 6), *DELHI, IST)["best_days"]
        b = M.find("puja", date(2026, 10, 6), date(2026, 10, 6), 13.0827, 80.2707, IST)["best_days"]
        assert a[0]["windows"][0]["start"] != b[0]["windows"][0]["start"]
