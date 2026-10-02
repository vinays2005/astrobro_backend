"""
Deterministic rule engine.

Rules evaluate chart facts and produce structured results.
The LLM synthesizes these results — it does NOT invent new rules.
All errors are surfaced explicitly; no silent fallbacks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.astrology.engine import Chart


@dataclass
class Rule:
    rule_id: str
    category: str
    description: str
    conditions: list[dict[str, Any]]
    weight: float = 1.0


@dataclass
class RuleResult:
    rule_id: str
    matched: bool
    strength: float
    factors: list[dict[str, Any]]
    interpretation: str
    category: str


class RuleEngine:
    """Evaluate deterministic astrology rules against a Chart."""

    def __init__(self) -> None:
        self._rules: list[Rule] = []
        self._register_all()

    # ── Public API ────────────────────────────────────────────

    def evaluate(self, chart: Chart, category: str) -> list[RuleResult]:
        """Return all matched rules for the given category."""
        results: list[RuleResult] = []
        errors: list[str] = []

        for rule in self._rules:
            if rule.category != category:
                continue
            try:
                matched, factors = self._evaluate_conditions(rule, chart)
            except Exception as exc:
                # Fail loud — collect errors, don't silently skip
                errors.append(f"rule {rule.rule_id}: {exc}")
                continue
            if matched:
                strength = self._compute_strength(rule, factors)
                results.append(RuleResult(
                    rule_id=rule.rule_id,
                    matched=True,
                    strength=strength,
                    factors=factors,
                    interpretation=rule.description,
                    category=category,
                ))

        if errors:
            # Return errors as a special result so caller can log/surface them
            results.append(RuleResult(
                rule_id="__errors__",
                matched=False,
                strength=0.0,
                factors=[{"errors": errors}],
                interpretation="Rule evaluation errors — see factors",
                category=category,
            ))

        return results

    def add_rule(self, rule: Rule) -> None:
        self._rules.append(rule)

    # ── Rule registration ─────────────────────────────────────

    def _register_all(self) -> None:
        self._register_career()
        self._register_marriage()
        self._register_finance()
        self._register_education()
        self._register_health()
        self._register_children()
        self._register_travel()
        self._register_spirituality()

    def _register_career(self) -> None:
        rules = [
            Rule("career_10th_lord_11th", "career",
                 "10th lord in 11th house — career gains through network and associations",
                 [{"field": "houses.10.lord", "op": "in_house", "value": [11]}]),
            Rule("career_10th_lord_10th", "career",
                 "10th lord in own 10th house — strong career, professional success",
                 [{"field": "houses.10.lord", "op": "in_house", "value": [10]}],
                 weight=1.3),
            Rule("career_saturn_10th", "career",
                 "Saturn in 10th house — career through discipline, slow steady rise, govt service",
                 [{"field": "planet_house", "planet": "Saturn", "value": [10]}]),
            Rule("career_sun_10th", "career",
                 "Sun in 10th house — leadership, authority, government career",
                 [{"field": "planet_house", "planet": "Sun", "value": [10]}],
                 weight=1.2),
            Rule("career_mars_10th", "career",
                 "Mars in 10th house — engineering, military, sports, competitive fields",
                 [{"field": "planet_house", "planet": "Mars", "value": [10]}]),
            Rule("career_mercury_10th", "career",
                 "Mercury in 10th house — IT, communication, writing, business",
                 [{"field": "planet_house", "planet": "Mercury", "value": [10]}]),
            Rule("career_10th_lord_6_8_12", "career",
                 "10th lord in dusthana (6/8/12) — career challenges, delays, setbacks",
                 [{"field": "houses.10.lord", "op": "in_house", "value": [6, 8, 12]}],
                 weight=0.9),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_marriage(self) -> None:
        rules = [
            Rule("marriage_7th_lord_kendra", "marriage",
                 "7th lord in kendra — supportive marriage prospects, stable partner",
                 [{"field": "houses.7.lord", "op": "in_house", "value": [1, 4, 7, 10]}]),
            Rule("marriage_7th_lord_trikona", "marriage",
                 "7th lord in trikona — auspicious marriage, compatible partner",
                 [{"field": "houses.7.lord", "op": "in_house", "value": [1, 5, 9]}]),
            Rule("marriage_venus_kendra", "marriage",
                 "Venus in kendra — romantic relationships, pleasant spouse",
                 [{"field": "planet_house", "planet": "Venus", "value": [1, 4, 7, 10]}]),
            Rule("marriage_saturn_7th", "marriage",
                 "Saturn in 7th house — delayed marriage, serious partner, long-term commitment",
                 [{"field": "planet_house", "planet": "Saturn", "value": [7]}]),
            Rule("marriage_mars_7th", "marriage",
                 "Mars in 7th house (Mangal Dosha) — energetic partner, possible conflicts, needs matching",
                 [{"field": "planet_house", "planet": "Mars", "value": [7]}]),
            Rule("marriage_7th_lord_dusthana", "marriage",
                 "7th lord in dusthana — marriage difficulties, separation risk",
                 [{"field": "houses.7.lord", "op": "in_house", "value": [6, 8, 12]}],
                 weight=0.8),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_finance(self) -> None:
        rules = [
            Rule("finance_2nd_11th_good", "finance",
                 "2nd and 11th lords not in dusthana — wealth accumulation, good income",
                 [
                     {"field": "houses.2.lord", "op": "not_in_house", "value": [6, 8, 12]},
                     {"field": "houses.11.lord", "op": "not_in_house", "value": [6, 8, 12]},
                 ]),
            Rule("finance_jupiter_2nd", "finance",
                 "Jupiter in 2nd house — wealth, financial wisdom, family prosperity",
                 [{"field": "planet_house", "planet": "Jupiter", "value": [2]}],
                 weight=1.2),
            Rule("finance_venus_2nd", "finance",
                 "Venus in 2nd house — wealth through luxury, arts, entertainment",
                 [{"field": "planet_house", "planet": "Venus", "value": [2]}]),
            Rule("finance_rahu_2nd", "finance",
                 "Rahu in 2nd house — unconventional wealth, foreign income, fluctuations",
                 [{"field": "planet_house", "planet": "Rahu", "value": [2]}]),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_education(self) -> None:
        rules = [
            Rule("education_mercury_jupiter_strong", "education",
                 "Mercury and Jupiter not debilitated — strong academic capacity",
                 [
                     {"field": "planet_dignity_score", "planet": "Mercury", "op": "gte", "value": 0.0},
                     {"field": "planet_dignity_score", "planet": "Jupiter", "op": "gte", "value": 0.0},
                 ]),
            Rule("education_5th_lord_kendra", "education",
                 "5th lord in kendra — intelligence, academic success",
                 [{"field": "houses.5.lord", "op": "in_house", "value": [1, 4, 7, 10]}],
                 weight=1.1),
            Rule("education_mercury_5th", "education",
                 "Mercury in 5th house — sharp memory, language skills",
                 [{"field": "planet_house", "planet": "Mercury", "value": [5]}]),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_health(self) -> None:
        rules = [
            Rule("health_sun_strong", "health",
                 "Sun in good dignity — strong vitality, resistance to illness",
                 [{"field": "planet_dignity_score", "planet": "Sun", "op": "gte", "value": 0.6}]),
            Rule("health_6th_lord_12th", "health",
                 "6th lord in 12th house — viparita raja yoga, diseases resolve, hospitalisation possible",
                 [{"field": "houses.6.lord", "op": "in_house", "value": [12]}]),
            Rule("health_saturn_lagna", "health",
                 "Saturn in 1st house — constitution may be slow/lean; chronic conditions possible but longevity",
                 [{"field": "planet_house", "planet": "Saturn", "value": [1]}]),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_children(self) -> None:
        rules = [
            Rule("children_5th_lord_strong", "children",
                 "5th lord in good dignity — children, good progeny, creativity",
                 [{"field": "planet_dignity_score", "planet_as_lord_of_house": 5, "op": "gte", "value": 0.0}]),
            Rule("children_jupiter_5th", "children",
                 "Jupiter in 5th house — blessed with children, wise offspring",
                 [{"field": "planet_house", "planet": "Jupiter", "value": [5]}],
                 weight=1.3),
            Rule("children_saturn_5th", "children",
                 "Saturn in 5th house — delayed children, smaller family, serious kids",
                 [{"field": "planet_house", "planet": "Saturn", "value": [5]}]),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_travel(self) -> None:
        rules = [
            Rule("travel_12th_lord_strong", "travel",
                 "12th lord well-placed — foreign travel, settlement abroad",
                 [{"field": "houses.12.lord", "op": "not_in_house", "value": [6, 8]}]),
            Rule("travel_rahu_9th_12th", "travel",
                 "Rahu in 9th or 12th house — foreign travel, unconventional journeys",
                 [{"field": "planet_house", "planet": "Rahu", "value": [9, 12]}]),
        ]
        for r in rules:
            self.add_rule(r)

    def _register_spirituality(self) -> None:
        rules = [
            Rule("spirituality_ketu_12th", "spirituality",
                 "Ketu in 12th house — moksha, past-life spiritual merit, asceticism",
                 [{"field": "planet_house", "planet": "Ketu", "value": [12]}],
                 weight=1.3),
            Rule("spirituality_jupiter_9th", "spirituality",
                 "Jupiter in 9th house — dharma, philosophy, guru connection",
                 [{"field": "planet_house", "planet": "Jupiter", "value": [9]}]),
            Rule("spirituality_saturn_12th", "spirituality",
                 "Saturn in 12th house — renunciation, isolation, spiritual practice",
                 [{"field": "planet_house", "planet": "Saturn", "value": [12]}]),
        ]
        for r in rules:
            self.add_rule(r)

    # ── Condition evaluation ──────────────────────────────────

    def _evaluate_conditions(
        self, rule: Rule, chart: Chart
    ) -> tuple[bool, list[dict[str, Any]]]:
        factors: list[dict[str, Any]] = []
        for cond in rule.conditions:
            value = self._resolve_field(chart, cond)
            if value is None:
                return False, []
            matched = self._apply_op(value, cond.get("op", "in_house"), cond["value"])
            if not matched:
                return False, []
            factors.append({"condition": cond, "resolved_value": value})
        return True, factors

    def _resolve_field(self, chart: Chart, cond: dict[str, Any]) -> Any:
        field_type = cond["field"]

        if field_type == "planet_house":
            planet = cond.get("planet")
            if planet is None or planet not in chart.planets:
                return None
            return chart.planets[planet].house

        if field_type == "planet_dignity_score":
            if "planet_as_lord_of_house" in cond:
                house_num = cond["planet_as_lord_of_house"]
                lord = chart.houses[house_num - 1].lord
                if lord not in chart.planets:
                    return None
                return chart.planets[lord].dignity_score
            planet = cond.get("planet")
            if planet is None or planet not in chart.planets:
                return None
            return chart.planets[planet].dignity_score

        # houses.N.lord → which house is that lord in?
        if field_type.startswith("houses."):
            parts = field_type.split(".")
            # e.g. "houses.10.lord" → house 10 lord → which house it occupies
            house_num = int(parts[1])
            attr = parts[2]
            if attr == "lord":
                lord = chart.houses[house_num - 1].lord
                if lord not in chart.planets:
                    return None
                return chart.planets[lord].house

        return None

    def _apply_op(self, value: Any, op: str, target: Any) -> bool:
        target_list = target if isinstance(target, list) else [target]
        if op in ("in_house", "in"):
            return value in target_list
        if op in ("not_in_house", "not_in"):
            return value not in target_list
        if op == "eq":
            return value == target
        if op == "gte":
            return value is not None and value >= target
        if op == "lte":
            return value is not None and value <= target
        return False

    def _compute_strength(self, rule: Rule, factors: list[dict[str, Any]]) -> float:
        base = 0.4 + 0.1 * len(factors)
        return round(min(1.0, max(0.0, base * rule.weight)), 4)
