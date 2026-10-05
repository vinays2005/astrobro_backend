"""Catalogue integrity and text preparation for the public-domain specialist books."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest

from app.rag.free_books import BATCH_ID, BY_ID, LORE_TERMS, MANIFEST, BookSpec, chunk_book, is_readable, prepare
from app.rag.scope import DOMAINS, HIDDEN_TITLES

SPEC = BookSpec(
    id="demo", title="Demo Book - Someone", author="Someone", year=1900, domain="tarot", topic_tags=("demo",),
    archive_id="demo-item", archive_file="demo_djvu.txt", license="Public domain", license_basis="test",
)

_SYLLABLES = ["ka", "lo", "mi", "re", "su", "ta", "vo", "ne", "pi", "do"]
_WORDS = [a + b + c for a in _SYLLABLES for b in _SYLLABLES for c in _SYLLABLES]     # 1000 distinct pseudo-words


def prose(sentences: int, start: int = 0) -> str:
    """Varied, readable text (no repeated sentences, which the readability check rightly rejects)."""
    out = []
    for i in range(start, start + sentences):
        words = [_WORDS[(i * 17 + j * 31) % len(_WORDS)] for j in range(18)]
        out.append(" ".join(words).capitalize() + ". ")
    return "".join(out)


class TestManifest:
    def test_every_book_is_fully_described(self):
        for b in MANIFEST:
            assert b.title and b.author and b.year and b.license and b.license_basis and b.topic_tags, b.id
            assert b.archive_id and b.archive_file.endswith(".txt"), b.id
            assert b.domain in DOMAINS, b.id

    def test_ids_and_files_are_unique(self):
        assert len({b.id for b in MANIFEST}) == len(MANIFEST) == len(BY_ID)
        assert len({b.local_file for b in MANIFEST}) == len(MANIFEST)

    def test_every_specialist_domain_has_a_book(self):
        assert {b.domain for b in MANIFEST} == set(DOMAINS)

    def test_all_patterns_compile(self):
        for b in MANIFEST:
            for pattern in (b.start, b.end, b.keep_if, *b.strip, *(p for p, _ in b.fixes)):
                if pattern:
                    re.compile(pattern, re.M)
            assert b.start_occurrence >= 1 and (b.min_hits >= 1)

    def test_filters_are_only_used_with_a_threshold(self):
        assert all(b.min_hits >= 1 for b in MANIFEST if b.keep_if)

    def test_new_books_are_never_hidden_from_their_own_topic(self):
        assert not {b.title for b in MANIFEST} & set(HIDDEN_TITLES)

    def test_only_old_works_are_listed(self):
        assert max(b.year for b in MANIFEST) <= 1926        # nothing under copyright anywhere
        assert all(b.license == "Public domain" for b in MANIFEST)

    def test_urls(self):
        assert SPEC.source_url == "https://archive.org/details/demo-item" and SPEC.local_file == "demo.txt"


class TestPrepare:
    def test_trims_to_the_body_and_drops_the_index(self):
        spec = replace(SPEC, start=r"^PREFACE$", end=r"^INDEX$")
        raw = "Title page\nContents\n\nPREFACE\nBody text here.\n\nINDEX\nA, 1\nB, 2\n"
        assert prepare(raw, spec) == "PREFACE Body text here."

    def test_a_later_occurrence_can_mark_the_start(self):
        spec = replace(SPEC, start=r"^INTRODUCTION$", start_occurrence=2)
        raw = "CONTENTS\nINTRODUCTION\n\nreal beginning\nINTRODUCTION\nthe actual text\n"
        assert prepare(raw, spec).startswith("INTRODUCTION the actual text")

    def test_missing_markers_keep_the_whole_text(self):
        spec = replace(SPEC, start=r"^NOWHERE$", end=r"^NEVER$")
        assert prepare("just some text", spec) == "just some text"

    def test_junk_lines_are_removed(self):
        spec = replace(SPEC, strip=(r"^.*Digitized by.*$", r"^\s*http://site\.example/.*$"))
        raw = "First line.\nDigitized by Google\nhttp://site.example/page [1 of 2]\nSecond line.\n"
        assert prepare(raw, spec) == "First line. Second line."

    def test_words_split_across_lines_are_rejoined_even_with_trailing_spaces(self):
        assert prepare("the remem- \nbered rule and a pro-\nceeding", SPEC) == "the remembered rule and a proceeding"

    def test_paragraphs_are_reflowed_but_kept_apart(self):
        assert prepare("one two\nthree\n\nfour\nfive\n", SPEC) == "one two three\n\nfour five"

    def test_systematic_scan_errors_can_be_fixed(self):
        spec = replace(SPEC, fixes=((r"\bm\b", "in"),))
        assert prepare("born m London and m Paris, a mother m", spec) == "born in London and in Paris, a mother in"

    def test_form_feeds_and_windows_line_endings(self):
        assert prepare("a\r\nb\x0cc\r\n", SPEC) == "a b c"


class TestReadability:
    def test_prose_is_readable(self):
        assert is_readable(prose(5))

    def test_number_tables_and_noise_are_not(self):
        assert not is_readable("1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 " * 6)
        assert not is_readable("%$# @@ ^^ ~~ ## 1234 ;; :: ,, .. " * 20)
        assert not is_readable("")

    def test_a_repeated_word_is_not_readable(self):
        assert not is_readable("Chapter " * 80)

    def test_short_fragments_are_not_readable(self):
        assert not is_readable("A few words only here.")


class TestChunking:
    def test_metadata_is_complete(self):
        chunks, stats = chunk_book(SPEC, prose(30))
        assert chunks and stats["kept"] == len(chunks)
        m = chunks[0].metadata
        assert m["book"] == "Demo Book - Someone" and m["domain"] == "tarot" and m["year"] == 1900
        assert m["license"] == "Public domain" and m["batch_id"] == BATCH_ID and m["source"].endswith("demo-item")
        assert m["topic_tags"] == ["demo"] and m["language"] == "eng" and m["tradition"] == "vedic"

    def test_chunk_ids_are_unique_and_stable(self):
        text = "\n\n".join(prose(2, start=i * 2) for i in range(40))
        a, _ = chunk_book(SPEC, text)
        b, _ = chunk_book(SPEC, text)
        assert len(a) > 5
        assert len({c.chunk_id for c in a}) == len(a) and [c.chunk_id for c in a] == [c.chunk_id for c in b]

    def test_unreadable_pieces_are_counted_and_dropped(self):
        text = prose(6) + "\n\n" + "12 34 56 78 90 " * 60 + "\n\n" + prose(6, start=50)
        chunks, stats = chunk_book(SPEC, text)
        assert chunks and stats["unreadable"] >= 1 and all(is_readable(c.text) for c in chunks)

    def test_topic_filter_needs_enough_different_terms(self):
        spec = replace(SPEC, keep_if=LORE_TERMS, min_hits=2)
        relevant = ("The rite of the Vrata begins when the Moon enters the lunar mansion and the planet Saturn is "
                    "favourable; the worshipper keeps a fast and offers a ruby and a pearl at the temple. ") * 2
        filler = prose(30, start=100)        # long enough that later chunks no longer overlap the relevant passage
        chunks, stats = chunk_book(spec, relevant + "\n\n" + filler)
        assert any("Vrata" in c.text for c in chunks) and stats["off_topic"] >= 1
        assert not any(filler[-60:] in c.text for c in chunks)

    def test_one_term_repeated_is_not_enough(self):
        spec = replace(SPEC, keep_if=LORE_TERMS, min_hits=2)
        text = ("The temple stood by the river and the old temple gate was open while the temple bell rang over "
                "the quiet town as the temple priest walked home slowly in the cool evening air. ") * 2
        chunks, stats = chunk_book(spec, text)
        assert not chunks and stats["off_topic"] >= 1

    def test_volumes_of_one_work_share_a_duplicate_filter(self):
        seen: set[str] = set()
        first, _ = chunk_book(SPEC, prose(8), seen=seen)
        second, stats = chunk_book(SPEC, prose(8), seen=seen)
        assert first and not second and stats["duplicate"] >= 1

    def test_no_chunk_exceeds_the_size_limit_by_much(self):
        chunks, _ = chunk_book(SPEC, "\n\n".join(prose(2, start=i * 2) for i in range(30)))
        assert chunks and max(len(c.text) for c in chunks) < 1500


@pytest.mark.parametrize("book_id", ["dutt-agni-purana-v2"])
def test_overlapping_volume_is_read_from_the_chapter_after_the_previous_volume_ends(book_id):
    """Volume 1 holds chapters 1-168; volume 2 repeats 87-168 with noisier OCR, so it starts at chapter 169."""
    spec = BY_ID[book_id]
    raw = "CHAPTER LXXXVII.\nold overlapping text\n\nCHAPTER CLXIX.\nnew material\n"
    assert prepare(raw, spec) == "CHAPTER CLXIX. new material"
