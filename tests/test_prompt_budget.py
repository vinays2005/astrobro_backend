"""The chat prompt has a token budget: long book passages are cut, short ones are left alone."""
from app.agents.orchestrator import _EVIDENCE_CHUNK_CHARS, _EVIDENCE_TOTAL_CHARS, _trim_evidence
from app.llm.prompts import SYSTEM_ASTROLOGER, system_prompt


def _chunk(text: str, book: str = "B") -> dict:
    return {"text": text, "metadata": {"book": book}}


def test_short_passages_are_untouched():
    chunks = [_chunk("Saturn in the 7th delays marriage."), _chunk("Jupiter aspects bring support.")]
    assert _trim_evidence(chunks) == chunks


def test_a_long_passage_is_cut_at_a_sentence_end():
    sentence = "Saturn in the sixth house gives strength against enemies. "
    out = _trim_evidence([_chunk(sentence * 40)])
    text = out[0]["text"]
    assert len(text) <= _EVIDENCE_CHUNK_CHARS
    assert text.endswith(". ...")                 # cut after a full sentence, then marked as cut


def test_total_size_is_capped_and_the_best_ranked_passages_are_kept_first():
    chunks = [_chunk("A" * 880, "first"), _chunk("B" * 880, "second"), _chunk("C" * 880, "third"), _chunk("D" * 880, "fourth")]
    out = _trim_evidence(chunks)
    assert sum(len(c["text"]) for c in out) <= _EVIDENCE_TOTAL_CHARS
    assert [c["metadata"]["book"] for c in out][:2] == ["first", "second"]


def test_the_book_name_survives_trimming():
    out = _trim_evidence([_chunk("word " * 500, "Brihat Parashara")])
    assert out[0]["metadata"] == {"book": "Brihat Parashara"}


def test_no_evidence_stays_empty():
    assert _trim_evidence([]) == []


def test_plain_text_chat_is_not_told_to_return_json():
    assert "valid JSON" in system_prompt(None)
    assert system_prompt(None) == SYSTEM_ASTROLOGER
    assert "valid JSON" not in system_prompt(None, json_output=False)
