"""Ashtakoota / Guna Milan: tables, scoring and cancellations (pins the corrected data)."""
from __future__ import annotations

import pytest

from app.astrology import matching as M
from app.astrology.constants import NAKSHATRAS

# PyJHora's published 7x7 Graha Maitri grid; order Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn
_GM_ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
_GM_GRID = [
    [5.0, 5.0, 5.0, 4.0, 5.0, 0.0, 0.0],
    [5.0, 5.0, 4.0, 1.0, 4.0, 0.5, 0.5],
    [5.0, 4.0, 5.0, 0.5, 5.0, 3.0, 0.5],
    [4.0, 1.0, 0.5, 5.0, 0.5, 5.0, 4.0],
    [5.0, 4.0, 5.0, 0.5, 5.0, 0.5, 3.0],
    [0.0, 0.5, 3.0, 5.0, 0.5, 5.0, 5.0],
    [0.0, 0.5, 0.5, 4.0, 3.0, 5.0, 5.0],
]


def moon(nak: int, sign: int | None = None, frac: float = 0.5) -> M.MoonPlacement:
    """A placement inside nakshatra `nak` (and, if given, forced into sign `sign`)."""
    lon = (nak + frac) * M.NAK_SPAN
    if sign is not None and int(lon / 30) != sign:
        lon = sign * 30 + 15.0
    return M.MoonPlacement(lon)


class TestTables:
    def test_each_gana_has_nine_nakshatras(self):
        assert [M.NAK_GANA.count(g) for g in (0, 1, 2)] == [9, 9, 9]

    @pytest.mark.parametrize("name,gana", [
        ("Ashwini", "Deva"), ("Mrigashira", "Deva"), ("Swati", "Deva"), ("Revati", "Deva"),
        ("Rohini", "Manushya"), ("Ardra", "Manushya"), ("Purva Ashadha", "Manushya"), ("Uttara Bhadrapada", "Manushya"),
        ("Magha", "Rakshasa"), ("Chitra", "Rakshasa"), ("Jyeshtha", "Rakshasa"), ("Shatabhisha", "Rakshasa"),
    ])
    def test_gana_assignments(self, name, gana):
        assert M.GANA_NAMES[M.NAK_GANA[NAKSHATRAS.index(name)]] == gana

    def test_yoni_matrix_is_symmetric_with_perfect_diagonal(self):
        n = len(M.YONI_ANIMALS)
        for i in range(n):
            assert M.YONI_MATRIX[i][i] == 4
            for j in range(n):
                assert M.YONI_MATRIX[i][j] == M.YONI_MATRIX[j][i]

    @pytest.mark.parametrize("a,b", [("Cat", "Rat"), ("Elephant", "Lion"), ("Cow", "Tiger"), ("Horse", "Buffalo"),
                                     ("Sheep", "Monkey"), ("Serpent", "Mongoose"), ("Dog", "Deer")])
    def test_sworn_enemy_yonis_score_zero(self, a, b):
        i, j = M.YONI_ANIMALS.index(a), M.YONI_ANIMALS.index(b)
        assert M.YONI_MATRIX[i][j] == 0

    def test_pushya_is_sheep_like_krittika(self):
        assert M.NAK_YONI[NAKSHATRAS.index("Pushya")] == M.NAK_YONI[NAKSHATRAS.index("Krittika")]

    def test_each_nadi_has_nine_nakshatras(self):
        assert [M.NAK_NADI.count(n) for n in (0, 1, 2)] == [9, 9, 9]

    def test_graha_maitri_matches_published_grid(self):
        for i, a in enumerate(_GM_ORDER):
            for j, b in enumerate(_GM_ORDER):
                assert M.graha_maitri_score(a, b) == _GM_GRID[i][j], (a, b)


class TestKootas:
    def test_tara_good_and_bad_counts(self):
        # Ashwini(0) and Bharani(1): counts 2 and 28 -> remainders 2 and 1, both fine
        assert M.ashtakoota(moon(1), moon(0))["breakdown"]["tara"]["score"] == 3.0
        # Ashwini(0) and Krittika(2): counts 3 (Vipat) and 26 -> remainder 8 -> only one bad
        assert M.ashtakoota(moon(2), moon(0))["breakdown"]["tara"]["score"] == 1.5

    @pytest.mark.parametrize("boy_sign,girl_sign,relation", [(0, 1, "2/12"), (0, 4, "5/9"), (0, 5, "6/8")])
    def test_bhakoot_dosha_pairs_score_zero(self, boy_sign, girl_sign, relation):
        r = M.ashtakoota(moon(0, boy_sign), moon(9, girl_sign))["breakdown"]["bhakut"]
        assert r["score"] == 0.0 and r["relation"] == relation

    def test_bhakoot_ok_for_other_pairs(self):
        assert M.ashtakoota(moon(0, 0), moon(9, 2))["breakdown"]["bhakut"]["score"] == 7.0  # 1st and 3rd

    def test_same_nadi_scores_zero_different_scores_eight(self):
        same = M.ashtakoota(moon(0), moon(5))["breakdown"]["nadi"]
        diff = M.ashtakoota(moon(0), moon(1))["breakdown"]["nadi"]
        assert same["score"] == 0.0 and diff["score"] == 8.0

    def test_vashya_splits_sagittarius_and_capricorn_by_degree(self):
        assert M._vashya_group(M.MoonPlacement(8 * 30 + 5)) == 1    # Sagittarius first half: Manava
        assert M._vashya_group(M.MoonPlacement(8 * 30 + 20)) == 0   # second half: Chatushpada
        assert M._vashya_group(M.MoonPlacement(9 * 30 + 5)) == 0    # Capricorn first half: Chatushpada
        assert M._vashya_group(M.MoonPlacement(9 * 30 + 20)) == 2   # second half: Jalachara

    def test_total_equals_sum_and_is_bounded(self):
        for b in range(0, 27, 4):
            for g in range(1, 27, 5):
                r = M.ashtakoota(moon(b), moon(g))
                assert r["total_score"] == round(sum(v["score"] for v in r["breakdown"].values()), 1)
                assert 0 <= r["total_score"] <= 36
                assert {v["max"] for v in r["breakdown"].values()} == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_identical_charts_score_high_but_nadi_dosha(self):
        r = M.ashtakoota(moon(10), moon(10))
        assert r["breakdown"]["nadi"]["score"] == 0.0
        assert r["doshas"]["nadi"]["present"]


class TestCancellations:
    def test_bhakoot_cancelled_by_friendly_lords(self):
        # Taurus (Venus) and Capricorn (Saturn) are 5/9 apart but their lords are friends
        r = M.ashtakoota(moon(3, 1), moon(21, 9))
        assert r["breakdown"]["bhakut"]["score"] == 0.0
        assert r["doshas"]["bhakoot"]["cancelled"] is True

    def test_nadi_cancelled_for_same_sign_different_nakshatra(self):
        # Krittika and Rohini both occupy Taurus and share the Antya nadi
        boy, girl = M.MoonPlacement(35.0), M.MoonPlacement(45.0)
        assert boy.sign_index == girl.sign_index == 1 and boy.nak_index != girl.nak_index
        d = M.ashtakoota(boy, girl)["doshas"]["nadi"]
        assert d["present"] and d["cancelled"]
        assert "Same Moon sign but different nakshatra" in d["cancellation_reasons"]

    def test_nadi_cancelled_for_same_nakshatra_different_pada(self):
        boy, girl = M.MoonPlacement(1.0), M.MoonPlacement(10.0)  # Ashwini pada 1 and pada 4
        assert boy.nak_index == girl.nak_index and boy.pada != girl.pada
        d = M.ashtakoota(boy, girl)["doshas"]["nadi"]
        assert d["present"] and "Same nakshatra but different pada" in d["cancellation_reasons"]

    def test_nadi_not_cancelled_when_nothing_applies(self):
        # Ashwini (Aries, Mars) and Ardra (Gemini, Mercury) share Aadi; different signs, stars and lords
        d = M.ashtakoota(moon(0), moon(5))["doshas"]["nadi"]
        assert d["present"] and not d["cancelled"] and d["severity"] == "high"

    def test_gana_dosha_flagged_for_deva_rakshasa(self):
        d = M.ashtakoota(moon(0), moon(2))["doshas"]["gana"]   # Ashwini (Deva) with Krittika (Rakshasa)
        assert d["present"]

    def test_rajju_present_when_both_stars_share_a_body_part(self):
        # Mrigashira (5th) and Chitra (14th) are both Head Rajju
        r = M.additional_checks(moon(4), moon(13))["rajju"]
        assert r["present"] and r["boy_group"] == r["girl_group"] == "Head"

    def test_rajju_absent_for_different_body_parts(self):
        assert M.additional_checks(moon(4), moon(3))["rajju"]["present"] is False   # Head vs Neck

    def test_vedha_pairs(self):
        assert M.additional_checks(moon(0), moon(17))["vedha"]["present"]    # Ashwini (1) + Jyeshtha (18) = 19
        assert M.additional_checks(moon(1), moon(16))["vedha"]["present"]    # Bharani (2) + Anuradha (17) = 19
        assert not M.additional_checks(moon(0), moon(1))["vedha"]["present"]

    def test_mahendra_counts(self):
        assert M.additional_checks(moon(3), moon(0))["mahendra"]["favourable"]       # girl Ashwini -> boy Rohini = 4th star
        assert not M.additional_checks(moon(1), moon(0))["mahendra"]["favourable"]   # 2nd star

    def test_placement_from_indices_is_consistent(self):
        for nak, sign in [(0, 0), (3, 1), (13, 5), (26, 11)]:
            p = M.placement_from_indices(nak, sign)
            assert (p.nak_index, p.sign_index) == (nak, sign)

    def test_each_nakshatra_belongs_to_exactly_one_rajju(self):
        names = [M.rajju_group(i) for i in range(27)]
        assert len(names) == 27 and set(names) == {"Head", "Neck", "Stomach", "Waist", "Foot"}

    def test_compatibility_bands(self):
        assert [M.compatibility_band(x) for x in (35, 27, 20, 14, 8)] == ["Excellent", "Very Good", "Good", "Average", "Poor"]
