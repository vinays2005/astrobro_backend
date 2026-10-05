"""Calculated facts for the chat prompt: added when a question needs them, correct, small, and never fatal."""
from datetime import datetime, timezone

import pytest

from app.astrology.engine import AstrologyEngine
from app.llm import facts as F
from app.llm.prompts import CHAT_PROMPT, CHAT_STREAM_PROMPT, facts_block

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def chart():
    # Born 1995-08-15 10:30 Mumbai: Mars is in the 1st house, which IS a Manglik placement. The live chat once
    # answered "no Mangal dosha" for exactly this chart.
    return AstrologyEngine().calculate_chart(dt=datetime(1995, 8, 15, 10, 30), lat=19.076, lon=72.877, tz="Asia/Kolkata")


def test_mars_in_the_first_house_is_reported_as_manglik(chart):
    assert chart.planets["Mars"].house == 1
    text = F.verified_facts("Do I have Mangal dosha and what should I do?", chart, NOW)
    assert "Manglik (Kuja) Dosha: PRESENT" in text


def test_the_answer_lists_doshas_that_are_absent_too(chart):
    assert "Not present:" in F.verified_facts("Do I have any dosha?", chart, NOW)


def test_remedy_questions_get_engine_remedies_not_invented_ones(chart):
    text = F.verified_facts("What remedies can help with my stress?", chart, NOW)
    assert "Remedies chosen by the rule engine" in text and "Mantra:" in text
    assert "Om Shani Namah" not in text           # the model's own (wrong) mantras are not in the facts


def test_a_marriage_question_gets_only_the_manglik_check(chart):
    text = F.verified_facts("When will I get married?", chart, NOW)
    assert "Manglik" in text and "Kaal Sarp" not in text and "Pitru" not in text


def test_a_present_manglik_comes_with_its_classical_remedy(chart):
    text = F.verified_facts("When will I get married?", chart, NOW)
    assert "Classical remedy for it:" in text and "Hanuman Chalisa" in text


def test_timing_questions_get_the_next_dasha_periods(chart):
    text = F.verified_facts("When will my luck change?", chart, NOW)
    assert "Next dasha sub-periods:" in text


def test_a_plain_question_adds_nothing(chart):
    assert F.verified_facts("Tell me about my personality", chart, NOW) == ""
    assert facts_block("") == ""


def test_no_chart_or_no_question_adds_nothing(chart):
    assert F.verified_facts("Do I have Mangal dosha?", None, NOW) == ""
    assert F.verified_facts("", chart, NOW) == ""


def test_the_facts_stay_within_the_size_cap(chart):
    text = F.verified_facts("Do I have any dosha? What remedy and when will it end?", chart, NOW)
    assert 0 < len(text) <= F.MAX_FACT_CHARS


def test_a_failure_in_the_engine_never_breaks_the_chat(chart, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine down")
    monkeypatch.setattr(F.DO, "analyze", boom)
    assert F.verified_facts("Do I have Mangal dosha?", chart, NOW) == ""


def test_both_prompts_carry_the_block_and_format_without_it():
    kwargs = dict(chart_json="c", dasha_json="d", evidence_json="e", history_json="[]", question="q")
    for template in (CHAT_PROMPT, CHAT_STREAM_PROMPT):
        with_facts = template.format(**kwargs, facts_block=facts_block("Doshas: none"))
        without = template.format(**kwargs, facts_block="")
        assert "=== CALCULATED FACTS" in with_facts and "Doshas: none" in with_facts
        assert "=== CALCULATED FACTS" not in without
