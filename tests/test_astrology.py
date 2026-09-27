"""
Unit tests for the deterministic astrology engine.

These tests verify calculation correctness — no LLM involved.
"""
from __future__ import annotations

import pytest
from datetime import datetime

from app.astrology.engine import AstrologyEngine, Chart
from app.astrology.constants import SIGNS, DASHA_SEQUENCE
from app.rules.engine import RuleEngine


# Known birth: 15 Aug 1990, 14:30, Mumbai (19.0760°N, 72.8777°E)
_KNOWN_DT = datetime(1990, 8, 15, 14, 30)
_MUMBAI_LAT = 19.0760
_MUMBAI_LON = 72.8777
_MUMBAI_TZ = "Asia/Kolkata"


@pytest.fixture(scope="module")
def engine() -> AstrologyEngine:
    return AstrologyEngine(ayanamsa="LAHIRI")


@pytest.fixture(scope="module")
def chart(engine: AstrologyEngine) -> Chart:
    return engine.calculate_chart(
        dt=_KNOWN_DT, lat=_MUMBAI_LAT, lon=_MUMBAI_LON, tz=_MUMBAI_TZ
    )


class TestChartStructure:
    def test_has_ascendant(self, chart: Chart):
        asc = chart.ascendant
        assert "sign" in asc
        assert asc["sign"] in SIGNS
        assert 0 <= float(asc["degree"]) < 30

    def test_has_all_planets(self, chart: Chart):
        expected = {"Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"}
        assert expected <= set(chart.planets.keys())

    def test_twelve_houses(self, chart: Chart):
        assert len(chart.houses) == 12
        for i, h in enumerate(chart.houses):
            assert h.number == i + 1
            assert h.sign in SIGNS
            assert h.lord in {
                "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"
            }

    def test_planet_houses_valid(self, chart: Chart):
        for name, p in chart.planets.items():
            assert 1 <= p.house <= 12, f"{name} has invalid house {p.house}"
            assert p.sign in SIGNS
            assert 0 <= p.sign_degree < 30

    def test_ketu_opposite_rahu(self, chart: Chart):
        rahu = chart.planets["Rahu"]
        ketu = chart.planets["Ketu"]
        diff = abs(rahu.longitude - ketu.longitude) % 360
        if diff > 180:
            diff = 360 - diff
        assert abs(diff - 180) < 1.0, f"Rahu-Ketu diff should be ~180, got {diff}"

    def test_moon_nakshatra(self, chart: Chart):
        nak = chart.nakshatra_moon
        assert nak.name
        assert 1 <= nak.pada <= 4
        assert nak.lord in DASHA_SEQUENCE

    def test_dasha_sequence_length(self, chart: Chart):
        assert len(chart.dasha_sequence) >= 9

    def test_dasha_periods_contiguous(self, chart: Chart):
        for i in range(len(chart.dasha_sequence) - 1):
            current = chart.dasha_sequence[i]
            next_p = chart.dasha_sequence[i + 1]
            gap = abs((next_p.start - current.end).total_seconds())
            assert gap < 86400, f"Gap between dasha periods: {gap}s"

    def test_current_dasha_has_lord(self, chart: Chart):
        cd = chart.current_dasha
        assert cd.get("mahadasha") is not None
        assert cd["mahadasha"]["lord"] in DASHA_SEQUENCE

    def test_yogas_are_list(self, chart: Chart):
        assert isinstance(chart.yogas, list)
        for yoga in chart.yogas:
            assert "name" in yoga
            assert "description" in yoga
            assert "strength" in yoga
            assert 0 <= yoga["strength"] <= 1


class TestDignity:
    def test_exalted_sun_in_aries(self, engine: AstrologyEngine):
        # Sun at 10° Aries → exalted
        dig, score = engine._dignity("Sun", 0, 10.0)
        assert dig == "exalted"
        assert score == 1.0

    def test_debilitated_sun_in_libra(self, engine: AstrologyEngine):
        dig, score = engine._dignity("Sun", 6, 10.0)
        assert dig == "debilitated"
        assert score == -1.0


class TestRuleEngine:
    @pytest.fixture(scope="class")
    def rules(self):
        return RuleEngine()

    def test_evaluate_returns_list(self, rules: RuleEngine, chart: Chart):
        results = rules.evaluate(chart, "career")
        assert isinstance(results, list)

    def test_matched_rules_have_strength(self, rules: RuleEngine, chart: Chart):
        results = rules.evaluate(chart, "career")
        for r in results:
            if r.rule_id != "__errors__":
                assert 0.0 <= r.strength <= 1.0

    def test_unknown_category_returns_empty(self, rules: RuleEngine, chart: Chart):
        results = rules.evaluate(chart, "unknown_category_xyz")
        matched = [r for r in results if r.matched]
        assert len(matched) == 0

    def test_errors_collected_not_raised(self, rules: RuleEngine, chart: Chart):
        """Rule errors collected as results, never raised (fail-loud pattern)."""
        results = rules.evaluate(chart, "marriage")
        # Should complete without raising
        assert results is not None
