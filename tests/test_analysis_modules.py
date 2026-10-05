"""Dasha, doshas, remedies, matching report, intent routing and the notification feed."""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.astrology import dasha as D
from app.astrology import doshas as DO
from app.astrology import intent as IN
from app.astrology import match_report as MR
from app.astrology import notifications as NF
from app.astrology import remedies as R
from app.astrology import strength as S
from app.astrology.constants import NAKSHATRAS, SIGN_LORDS, SIGNS
from app.astrology.engine import AstrologyEngine

NOW = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]
# Spread across signs so that nothing is accidentally conjunct (nodes in Gemini/Sagittarius)
_DEFAULT = {"Sun": (4, 5.0), "Moon": (3, 5.0), "Mars": (0, 5.0), "Mercury": (5, 5.0), "Jupiter": (11, 5.0),
            "Venus": (1, 5.0), "Saturn": (10, 5.0), "Rahu": (2, 5.0), "Ketu": (8, 5.0)}


def fake_chart(asc: int, pos: dict[str, tuple[int, float]] | None = None, moon_nak: str = "Rohini"):
    placed = {**_DEFAULT, **(pos or {})}
    planets = {}
    for name in _PLANETS:
        sign, deg = placed[name]
        planets[name] = SimpleNamespace(name=name, longitude=sign * 30 + deg, sign=SIGNS[sign],
                                        house=((sign - asc) % 12) + 1, dignity="neutral", combust=False, retrograde=False)
    houses = [SimpleNamespace(number=i + 1, sign=SIGNS[(asc + i) % 12], lord=SIGN_LORDS[(asc + i) % 12],
                              occupants=[n for n, p in planets.items() if p.house == i + 1]) for i in range(12)]
    return SimpleNamespace(
        planets=planets, houses=houses, aspects={},
        ascendant={"sign_index": asc, "sign": SIGNS[asc], "lord": SIGN_LORDS[asc], "longitude": asc * 30 + 10.0},
        nakshatra_moon=SimpleNamespace(name=moon_nak, pada=1, index=NAKSHATRAS.index(moon_nak)),
        birth_datetime=datetime(1990, 1, 1), functional_nature={},
    )


@pytest.fixture(scope="module")
def real_chart():
    return AstrologyEngine().calculate_chart(dt=datetime(1990, 8, 15, 14, 30), lat=19.076, lon=72.8777, tz="Asia/Kolkata")


class TestDasha:
    def test_matches_engine_current_period(self, real_chart):
        tl = D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime)
        cur = D.period_at(tl, datetime.utcnow())
        eng = real_chart.current_dasha
        assert cur["maha"]["lord"] == eng["mahadasha"]["lord"]
        assert cur["antar"]["lord"] == eng["antardasha"]["lord"]
        assert cur["praty"]["lord"] == eng["pratyantardasha"]["lord"]

    def test_mahadashas_are_contiguous_and_follow_the_sequence(self, real_chart):
        tl = D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime)
        assert len(tl) == 9 and tl[0]["start"] == real_chart.birth_datetime and tl[0]["balance_at_birth"]
        for a, b in zip(tl, tl[1:]):
            assert a["end"] == b["start"]
        order = [m["lord"] for m in tl]
        assert order == [D.DASHA_SEQUENCE[(D.DASHA_SEQUENCE.index(order[0]) + i) % 9] for i in range(9)]
        assert tl[0]["lord"] == "Moon" and tl[0]["years"] < 10        # Rohini: Moon dasha, mostly elapsed at birth

    def test_antardashas_tile_each_mahadasha(self, real_chart):
        for maha in D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime):
            a = maha["antardashas"]
            assert a[0]["start"] == maha["start"] and abs((a[-1]["end"] - maha["end"]).total_seconds()) < 1
            for x, y in zip(a, a[1:]):
                assert abs((x["end"] - y["start"]).total_seconds()) < 1

    def test_full_mahadasha_lengths(self, real_chart):
        tl = D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime)
        for maha in tl[1:]:
            assert maha["years"] == D.DASHA_YEARS[maha["lord"]]

    def test_pratyantardashas_tile_an_antardasha(self, real_chart):
        tl = D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime)
        antar = tl[2]["antardashas"][3]
        sub = D.pratyantardashas(tl[2]["lord"], antar["lord"], antar["start"], antar["end"])
        assert len(sub) == 9 and sub[0]["start"] == antar["start"] and abs((sub[-1]["end"] - antar["end"]).total_seconds()) < 1

    def test_interpretation_is_chart_specific(self, real_chart):
        prof = D.lord_profile("Jupiter", real_chart.planets, real_chart.houses, real_chart.ascendant["sign_index"])
        assert prof["rules_houses"] == [2, 5] and prof["placed_house"] == 9
        text = D.interpret("Jupiter", prof)
        assert "2nd and 5th houses" in text and "9th house" in text

    def test_no_period_outside_the_timeline(self, real_chart):
        tl = D.build_timeline(real_chart.planets["Moon"].longitude, real_chart.birth_datetime)
        assert D.period_at(tl, datetime(2300, 1, 1)) is None


class TestManglik:
    def test_seventh_house_mars_is_high_and_uncancelled(self):
        m = DO.manglik(fake_chart(0, {"Mars": (6, 5.0), "Moon": (1, 5.0), "Venus": (2, 5.0)}))
        assert m["present"] and m["severity"] == "high" and m["cancellations"] == [] and m["mars_house"] == 7

    def test_exalted_mars_is_cancelled(self):
        m = DO.manglik(fake_chart(3, {"Mars": (9, 5.0), "Moon": (5, 5.0), "Venus": (6, 5.0)}))
        assert m["present"] and m["severity"] == "reduced"
        assert "Mars is exalted in Capricorn" in m["cancellations"]
        assert any("classical exception" in c for c in m["cancellations"])

    def test_own_sign_cancels(self):
        m = DO.manglik(fake_chart(1, {"Mars": (7, 5.0), "Moon": (5, 5.0), "Venus": (2, 5.0)}))   # Scorpio in the 7th
        assert m["present"] and "Mars is in its own sign" in m["cancellations"]

    def test_jupiter_conjunction_cancels(self):
        m = DO.manglik(fake_chart(0, {"Mars": (3, 5.0), "Jupiter": (3, 15.0), "Moon": (1, 5.0), "Venus": (5, 5.0)}))
        assert m["present"] and "Jupiter is conjunct Mars" in m["cancellations"]

    def test_not_manglik(self):
        m = DO.manglik(fake_chart(0, {"Mars": (2, 5.0), "Moon": (0, 5.0), "Venus": (5, 5.0)}))
        assert m["present"] is False and m["severity"] == "none"

    def test_only_from_the_moon_is_low(self):
        m = DO.manglik(fake_chart(0, {"Mars": (2, 5.0), "Moon": (11, 5.0), "Venus": (5, 5.0)}))
        assert m["present"] and m["severity"] == "low" and m["references"]["Moon"] == 4 and m["references"]["Lagna"] == 3


class TestOtherDoshas:
    def test_full_kaal_sarp_with_type_by_rahu_house(self):
        pos = {"Rahu": (0, 10.0), "Ketu": (6, 10.0), "Sun": (1, 5.0), "Moon": (2, 5.0), "Mars": (3, 5.0),
               "Mercury": (4, 5.0), "Jupiter": (4, 20.0), "Venus": (3, 20.0), "Saturn": (5, 10.0)}
        k = DO.kaal_sarp(fake_chart(0, pos))
        assert k["present"] and not k["partial"] and k["type"] == "Anant" and k["severity"] == "high"

    def test_partial_and_absent_kaal_sarp(self):
        base = {"Rahu": (0, 10.0), "Ketu": (6, 10.0), "Sun": (1, 5.0), "Moon": (2, 5.0), "Mars": (3, 5.0),
                "Mercury": (4, 5.0), "Jupiter": (4, 20.0), "Venus": (3, 20.0), "Saturn": (5, 10.0)}
        partial = DO.kaal_sarp(fake_chart(0, {**base, "Saturn": (8, 10.0)}))
        assert partial["present"] and partial["partial"] and partial["severity"] == "low"
        none = DO.kaal_sarp(fake_chart(0, {**base, "Saturn": (8, 10.0), "Venus": (9, 20.0), "Mars": (10, 5.0)}))
        assert none["present"] is False

    def test_all_twelve_kaal_sarp_names_exist(self):
        assert sorted(DO._KAALSARP_TYPES) == list(range(1, 13)) and DO._KAALSARP_TYPES[1] == "Anant"

    def test_surya_and_chandra_grahan(self):
        g = DO.grahan(fake_chart(0, {"Sun": (4, 10.0), "Rahu": (4, 20.0), "Ketu": (10, 20.0)}))
        surya, chandra = g
        assert surya["present"] and surya["severity"] == "high" and surya["orb"] == 10.0
        assert not chandra["present"]
        g2 = DO.grahan(fake_chart(0, {"Moon": (10, 1.0), "Ketu": (10, 20.0), "Rahu": (4, 20.0)}))
        assert g2[1]["present"] and g2[1]["severity"] == "moderate"

    def test_guru_chandala_and_angarak(self):
        c = fake_chart(0, {"Jupiter": (2, 5.0), "Rahu": (2, 25.0), "Ketu": (8, 25.0), "Mars": (2, 28.0)})
        out = {d["name"]: d for d in DO.analyze(c, NOW)["doshas"]}
        assert out["Guru Chandala Dosha"]["present"] and out["Angarak Dosha"]["present"]

    def test_pitru_dosha_when_rahu_in_ninth(self):
        p = DO.pitru(fake_chart(0, {"Rahu": (8, 5.0), "Ketu": (2, 5.0), "Jupiter": (6, 5.0)}))
        assert p["present"] and p["score"] >= 2

    def test_no_pitru_dosha_in_a_clean_chart(self):
        assert DO.pitru(fake_chart(2))["present"] is False      # nodes in the 1st and 7th, 9th lord Saturn unafflicted

    def test_saturn_ruled_ninth_house_is_not_flagged_for_being_with_itself(self):
        c = fake_chart(2)                                          # Gemini Lagna: 9th house is Aquarius, ruled by Saturn
        assert c.houses[8].lord == "Saturn"
        assert "conjunct a malefic" not in DO.pitru(c)["reason"]

    def test_gand_mool(self):
        assert DO.gand_mool(fake_chart(0, moon_nak="Mula"))["present"]
        assert not DO.gand_mool(fake_chart(0, moon_nak="Rohini"))["present"]

    def test_analyze_summary_counts_present_doshas(self):
        r = DO.analyze(fake_chart(0, {"Mars": (6, 5.0), "Moon": (1, 5.0), "Venus": (2, 5.0)}, moon_nak="Magha"), NOW)
        assert r["summary"]["count"] == len(r["summary"]["present"])
        assert {"Manglik (Kuja) Dosha", "Gand Mool Dosha"} <= set(r["summary"]["present"])
        assert all(d["remedy_key"] for d in r["doshas"]) and r["summary"]["note"]


class TestStrengthAndRemedies:
    def test_strength_scores_are_bounded_and_labelled(self, real_chart):
        for p in _PLANETS[:7]:
            s = S.planet_strength(real_chart, p)
            assert 5 <= s["score"] <= 98 and s["label"] in {"strong", "moderate", "weak"}
        h = S.house_strength(real_chart, 7)
        assert 5 <= h["score"] <= 98 and h["lord"] == real_chart.houses[6].lord

    def test_exalted_planet_beats_debilitated(self):
        good, bad = fake_chart(0), fake_chart(0)
        good.planets["Jupiter"].dignity, bad.planets["Jupiter"].dignity = "exalted", "debilitated"
        assert S.planet_strength(good, "Jupiter")["score"] > S.planet_strength(bad, "Jupiter")["score"]

    def test_personal_remedies_follow_the_running_dasha(self, real_chart):
        r = R.personal_remedies(real_chart, NOW)
        assert r["running_dasha"] == {"mahadasha": "Jupiter", "antardasha": "Venus"}
        by_planet = {x["planet"]: x for x in r["remedies"]}
        assert by_planet["Jupiter"]["mode"] == "strengthen" and "gemstone" in by_planet["Jupiter"]
        assert "gemstone" not in by_planet["Venus"]        # Venus rules the 7th and 12th for Scorpio Lagna
        assert all(("gemstone" in x) == (x["mode"] == "strengthen") for x in r["remedies"])
        assert len(r["remedies"]) <= 5 and r["disclaimer"]

    def test_every_planet_has_complete_remedies(self):
        for planet, rem in R.PLANET_REMEDIES.items():
            assert {"gemstone", "mantra", "deity", "fast_day", "donate", "donate_day", "colour", "rudraksha"} <= set(rem), planet
            assert rem["mantra"]["beej"].startswith("Om ")

    def test_dosha_remedies_ignore_unknown_keys(self):
        out = R.dosha_remedies(["manglik", "no_such_dosha", "pitru"])
        assert [x["dosha"] for x in out] == ["manglik", "pitru"]

    def test_every_dosha_key_has_remedies(self, real_chart):
        keys = {d["remedy_key"] for d in DO.analyze(real_chart, NOW)["doshas"]}
        assert keys <= set(R.DOSHA_REMEDIES)


class TestMatchReport:
    def test_manglik_compatibility_cases(self):
        strong = {"present": True, "cancellations": [], "severity": "high"}
        none = {"present": False, "cancellations": [], "severity": "none"}
        cancelled = {"present": True, "cancellations": ["x"], "severity": "high"}
        assert MR.manglik_compatibility(strong, strong)["balanced"]
        assert MR.manglik_compatibility(none, none)["balanced"]
        mismatch = MR.manglik_compatibility(strong, none)
        assert not mismatch["balanced"] and "groom" in mismatch["verdict"]
        assert "bride" in MR.manglik_compatibility(none, strong)["verdict"]
        assert MR.manglik_compatibility(cancelled, none)["balanced"]

    def test_verdict_levels(self):
        ok = {k: {"present": False, "cancelled": False} for k in ("nadi", "bhakoot", "gana")}
        balanced, rajju_ok = {"balanced": True}, {"present": False}
        assert MR.verdict(28, ok, balanced, rajju_ok)["level"] == "Highly recommended"
        nadi = {**ok, "nadi": {"present": True, "cancelled": False}}
        assert MR.verdict(22, nadi, balanced, rajju_ok)["level"] == "Recommended with remedies"
        both = {**nadi, "bhakoot": {"present": True, "cancelled": False}}
        assert MR.verdict(22, both, balanced, rajju_ok)["level"] == "Acceptable with caution"
        assert MR.verdict(14, ok, balanced, rajju_ok)["level"].startswith("Not recommended")
        cancelled = {**ok, "nadi": {"present": True, "cancelled": True}}
        assert MR.verdict(28, cancelled, balanced, rajju_ok)["concerns"] == []

    def test_full_report_structure(self, real_chart):
        girl = AstrologyEngine().calculate_chart(dt=datetime(1992, 3, 2, 9, 10), lat=28.6139, lon=77.2090, tz="Asia/Kolkata")
        r = MR.full_report(real_chart, girl, "Arjun", "Meera", NOW)
        assert r["guna_milan"]["max_score"] == 36 and 0 <= r["guna_milan"]["total_score"] <= 36
        assert {"nadi", "bhakoot", "gana", "rajju", "vedha"} <= set(r["doshas"])
        assert set(r["areas"]) == {"emotional", "physical", "communication", "finances", "family_life", "children",
                                   "health_and_longevity_of_union"}
        assert all(0 <= a["score"] <= 100 for a in r["areas"].values())
        assert r["boy"]["name"] == "Arjun" and r["girl"]["name"] == "Meera"
        assert r["verdict"]["level"] and r["disclaimer"]
        for who in ("boy", "girl"):
            prof = r["marriage_profiles"][who]
            assert prof["navamsa"]["lagna"] in SIGNS and 0 <= prof["marriage_score"] <= 100

    def test_marriage_windows_are_in_the_future_and_linked_to_indicators(self, real_chart):
        wins = MR.marriage_windows(real_chart, "male", NOW)
        assert wins and all(w["end"] >= "2026-10-05" for w in wins)
        assert all(w["strength"] in {"strong", "supportive"} for w in wins)

    def test_navamsa_lagna_is_a_valid_sign(self, real_chart):
        assert 0 <= MR.navamsa_lagna(real_chart) < 12


class TestLove:
    def test_flames_known_result(self):
        assert MR.flames("Anil", "Sunita") == "Enemies"    # 4 unmatched letters -> E (worked by hand)
        assert MR.flames("Ram", "Ram") == "Marriage"       # no unmatched letters

    def test_name_score_is_a_two_digit_number(self):
        for a, b in [("Arjun", "Meera"), ("Romeo", "Juliet"), ("A", "B")]:
            assert 10 <= MR.name_score(a, b) <= 99

    def test_love_without_birth_details(self):
        r = MR.love_calculation("Arjun", "Meera")
        assert "astrological" not in r and r["love_percentage"] == r["name_score"] and 30 <= r["name_score"] <= 99

    def test_love_blends_astrology_when_available(self, real_chart):
        m = MR.moon_placement(real_chart)
        r = MR.love_calculation("Arjun", "Meera", m, m)
        assert r["astrological"]["percentage"] == round(r["astrological"]["guna_milan"] / 36 * 100)
        assert r["love_percentage"] == round(0.7 * r["astrological"]["percentage"] + 0.3 * r["name_score"])


class TestIntent:
    @pytest.mark.parametrize("text,category", [
        ("When will I get a promotion in my job?", "career"),
        ("Will I get married this year? We are planning a wedding", "marriage"),
        ("kab hogi meri shaadi", "marriage"),
        ("My mother is sick and in hospital", "health"),
        ("Should I start a business with my partner?", "business"),
        ("what is the meaning of the number 7", "numerology"),
        ("Which date is auspicious for griha pravesh", "muhurat"),
        ("Is my kitchen direction right as per vastu", "vastu"),
        ("pick a tarot card for me", "tarot"),
        ("How is the sky today? nothing relevant", "general"),
    ])
    def test_categories(self, text, category):
        assert IN.classify(text)["category"] == category

    def test_crisis_language_is_never_routed_to_astrology(self):
        for text in ("I want to end my life", "I have no reason to live, nothing is working at work", "suicidal thoughts"):
            r = IN.classify(text)
            assert r["category"] == "support" and r["suggested_modules"] == [] and r["astrologer_specialty"] is None
            assert r["safety"]["level"] == "crisis" and "14416" in r["safety"]["message"]

    def test_sensitive_categories_carry_a_disclaimer(self):
        assert "doctor" in IN.classify("my health and surgery")["disclaimer"]
        assert "lawyer" in IN.classify("I have a court case")["disclaimer"]

    def test_confidence_and_alternatives(self):
        r = IN.classify("love and career both matter")
        assert 0 < r["confidence"] <= 1 and r["alternatives"]


class TestNotificationFeed:
    def test_feed_contents_and_stability(self, real_chart):
        kw = dict(chart=real_chart, name="Arjun", dob=date(1990, 8, 15), start=date(2026, 8, 10), days=14,
                  lat=28.6139, lon=77.2090, tz="Asia/Kolkata", now=NOW)
        a, b = NF.build_feed(**kw), NF.build_feed(**kw)
        assert a == b and [i["id"] for i in a["items"]] == [i["id"] for i in b["items"]]
        ids = [i["id"] for i in a["items"]]
        assert len(ids) == len(set(ids))
        assert a["items"] == sorted(a["items"], key=lambda i: (i["date"], 0 if i["priority"] == "high" else 1, i["type"]))
        types = {i["type"] for i in a["items"]}
        assert "daily_horoscope" in types and "birthday" in types
        assert sum(i["type"] == "daily_horoscope" for i in a["items"]) == 14
        bday = next(i for i in a["items"] if i["type"] == "birthday")
        assert bday["date"] == "2026-08-15" and bday["priority"] == "high"

    def test_feed_includes_festivals_and_transits(self, real_chart):
        feed = NF.build_feed(real_chart, "Arjun", date(1990, 8, 15), date(2026, 10, 25), 30, 28.6139, 77.2090, "Asia/Kolkata", NOW)
        titles = " | ".join(i["title"] for i in feed["items"])
        assert "Diwali" in titles and "Jupiter enters Leo" in titles
        assert all(i["deep_link"] for i in feed["items"])
