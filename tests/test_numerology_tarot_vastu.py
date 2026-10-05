"""Numerology, Tarot and Vastu."""
from __future__ import annotations

from datetime import date

import pytest

from app.astrology import numerology as N
from app.astrology import tarot as TR
from app.astrology import vastu as V


class TestNumerology:
    @pytest.mark.parametrize("dob,expected", [
        (date(1990, 8, 15), 6),     # 8 + 6 + 1 = 15 -> 6
        (date(1975, 12, 25), 5),    # 3 + 7 + 22(master kept) = 32 -> 5
        (date(1960, 11, 29), 11),   # 11 + 11 + 7 = 29 -> 11 (master kept)
        (date(2000, 1, 1), 4),
    ])
    def test_life_path_by_hand(self, dob, expected):
        assert N.life_path(dob) == expected

    def test_reduce_number_masters(self):
        assert N.reduce_number(29) == 11 and N.reduce_number(29, keep_master=False) == 2
        assert N.reduce_number(44) == 8 and N.reduce_number(33) == 33 and N.reduce_number(9) == 9

    def test_indian_numbers(self):
        assert N.mulank(date(1990, 8, 15)) == 6          # day 15 -> 6
        assert N.bhagyank(date(1990, 8, 15)) == 6        # 33 -> 6
        assert N.mulank(date(2000, 11, 29)) == 2

    def test_name_numbers_for_john_smith(self):
        p = N.profile("John Smith", date(1990, 8, 15), date(2026, 10, 5))
        assert p["destiny"]["number"] == 8               # 20 + 24 = 44 -> 8
        assert p["personality"]["number"] == 11          # consonants total 29 -> 11 (master)
        assert p["soul_urge"]["number"] == 6             # vowels O, I

    def test_y_counts_as_a_vowel_only_when_the_word_has_none(self):
        lynn = dict(N._word_letters("Lynn"))
        assert N._word_letters("Lynn")[1] == ("Y", True)
        assert N._word_letters("Mary")[-1] == ("Y", False)
        assert lynn["L"] is False

    def test_personal_cycle(self):
        p = N.profile("A B", date(1990, 8, 15), date(2026, 10, 5))["personal_cycle"]
        assert p["year"]["number"] == 6                   # 8 + 6 + (2026 -> 1) = 15 -> 6
        assert p["month"]["number"] == 7                  # 6 + 10 -> 16 -> 7
        assert 1 <= p["day"]["number"] <= 9

    def test_profile_is_deterministic_and_complete(self):
        a = N.profile("Arjun Sharma", date(1990, 8, 15), date(2026, 10, 5))
        assert a == N.profile("Arjun Sharma", date(1990, 8, 15), date(2026, 10, 5))
        for key in ("life_path", "destiny", "soul_urge", "personality", "birthday"):
            assert a[key]["title"] and a[key]["meaning"] and a[key]["strengths"]
        assert a["indian"]["ruling_planet"] == "Venus" and a["indian"]["lucky_day"] == "Friday"

    def test_non_latin_letters_are_ignored_when_english_letters_exist(self):
        p = N.profile("राम Ram", date(1990, 1, 1), date(2026, 1, 1))
        assert p["destiny"]["number"] == N.profile("Ram", date(1990, 1, 1), date(2026, 1, 1))["destiny"]["number"]

    def test_names_without_vowels_or_consonants_do_not_crash(self):
        p = N.profile("A", date(1990, 1, 1), date(2026, 1, 1))              # no consonants
        assert p["personality"]["number"] is None and p["soul_urge"]["number"] == 1
        q = N.profile("Hmm", date(1990, 1, 1), date(2026, 1, 1))            # no vowels
        assert q["soul_urge"]["number"] is None and q["personality"]["number"] is not None
        c = N.compatibility("A", date(1990, 1, 1), "Hmm", date(1992, 3, 2))
        assert 0 <= c["score"] <= 100

    def test_name_with_no_english_letters_is_rejected(self):
        for bad in ("राम", "123", "  "):
            with pytest.raises(ValueError):
                N.profile(bad, date(1990, 1, 1), date(2026, 1, 1))

    def test_compatibility_symmetric_and_bounded(self):
        a = N.compatibility("Arjun", date(1990, 8, 15), "Meera", date(1992, 3, 2))
        b = N.compatibility("Meera", date(1992, 3, 2), "Arjun", date(1990, 8, 15))
        assert a["score"] == b["score"] and 0 <= a["score"] <= 100
        assert a["label"] in {"excellent", "good", "moderate", "needs effort"}

    def test_daily_number(self):
        d = N.daily_number(date(1990, 8, 15), date(2026, 10, 5))
        assert 1 <= d["number"] <= 9 and d["ruling_planet"]

    def test_every_number_has_a_profile(self):
        assert set(N.NUMBER_PROFILES) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 22, 33}


class TestTarot:
    def test_deck_is_complete_and_unique(self):
        assert len(TR.DECK) == 78
        assert len({c["id"] for c in TR.DECK}) == 78 and len({c["name"] for c in TR.DECK}) == 78
        assert sum(c["arcana"] == "major" for c in TR.DECK) == 22
        assert all(len(c["upright_keywords"]) == 3 and c["upright"] and c["reversed"] for c in TR.DECK)

    def test_every_tone_card_exists(self):
        names = {c["name"] for c in TR.DECK}
        assert TR._POSITIVE <= names and TR._NEGATIVE <= names

    def test_every_spread_position_has_a_frame(self):
        for spread, positions in TR.SPREADS.items():
            assert all(p in TR._POSITION_FRAMES for p in positions), spread

    def test_seeded_draw_is_reproducible(self):
        assert TR.draw("three_card", seed="abc") == TR.draw("three_card", seed="abc")
        assert TR.draw("three_card", seed="abc") != TR.draw("three_card", seed="xyz")

    def test_no_duplicate_cards_in_a_spread(self):
        r = TR.draw("celtic_cross", seed=1)
        assert len({x["card"]["id"] for x in r["readings"]}) == 10

    def test_spread_sizes(self):
        assert {k: len(v) for k, v in TR.SPREADS.items()} == {
            "single": 1, "three_card": 3, "yes_no": 1, "love": 5, "career": 5, "decision": 3, "celtic_cross": 10}

    def test_yes_no_answer_follows_card_tone(self):
        seen = set()
        for seed in range(60):
            r = TR.draw("yes_no", seed=seed)
            reading = r["readings"][0]
            expected = "Yes" if reading["tone"] > 0 else "No" if reading["tone"] < 0 else "Maybe"
            assert r["answer"]["result"] == expected
            seen.add(expected)
        assert seen == {"Yes", "No", "Maybe"}

    def test_reversals_can_be_switched_off(self):
        assert not any(r["reversed"] for seed in range(30) for r in TR.draw("celtic_cross", seed=seed, allow_reversed=False)["readings"])

    def test_reversal_rate_is_reasonable(self):
        n = sum(r["reversed"] for seed in range(200) for r in TR.draw("three_card", seed=seed)["readings"])
        assert 0.25 < n / 600 < 0.45

    def test_card_of_the_day_is_stable_per_user_and_date(self):
        a = TR.card_of_the_day(date(2026, 10, 5), "u1")["readings"][0]["card"]["id"]
        assert a == TR.card_of_the_day(date(2026, 10, 5), "u1")["readings"][0]["card"]["id"]
        assert any(TR.card_of_the_day(date(2026, 10, 5), f"u{i}")["readings"][0]["card"]["id"] != a for i in range(2, 12))

    def test_love_spread_adds_area_notes_and_unknown_spread_fails(self):
        r = TR.draw("love", seed=3)
        assert all(x["area_note"] for x in r["readings"])
        with pytest.raises(ValueError):
            TR.draw("nonsense")

    def test_tone_flips_when_reversed(self):
        tower = TR.get_card("major-16")
        assert TR.tone(tower, False) == -1 and TR.tone(tower, True) == 1


class TestVastu:
    def test_ideal_acceptable_and_avoid(self):
        assert V.evaluate("kitchen", "SE")["status"] == "ideal"
        assert V.evaluate("kitchen", "NW")["status"] == "acceptable"
        bad = V.evaluate("kitchen", "NE")
        assert bad["status"] == "avoid" and bad["remedy"] and bad["score"] < 50

    def test_direction_aliases(self):
        assert V.normalize_direction("North-East") == "NE" and V.normalize_direction("south west") == "SW"
        assert V.normalize_direction(" centre ") == "CENTER" and V.normalize_direction("n") == "N"

    def test_room_normalisation(self):
        assert V.normalize_room("Pooja Room") == "pooja_room" and V.normalize_room("master-bedroom") == "master_bedroom"

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            V.evaluate("kitchen", "UP")
        with pytest.raises(ValueError):
            V.evaluate("swimming_pool", "N")

    def test_every_rule_references_valid_directions(self):
        for room, rule in V.RULES.items():
            for key in ("ideal", "acceptable", "avoid"):
                assert set(rule[key]) <= set(V.DIRECTIONS), (room, key)
            assert not (set(rule["ideal"]) & set(rule["avoid"])), room

    def test_analyze_groups_findings_and_scores(self):
        r = V.analyze("NE", {"kitchen": "SE", "toilet": "NE", "pooja_room": "NE", "master_bedroom": "SW"})
        assert len(r["findings"]) == 5 and r["overall_score"] == round(sum(f["score"] for f in r["findings"]) / 5)
        assert [f["room"] for f in r["needs_attention"]] == ["toilet"]
        assert r["disclaimer"] and r["general_tips"]

    def test_guidelines_cover_all_rooms(self):
        g = V.guidelines()
        assert set(g["rooms"]) == set(V.RULES) and set(g["directions"]) == set(V.DIRECTIONS)
