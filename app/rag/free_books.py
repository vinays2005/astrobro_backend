"""Catalogue and text preparation for the public-domain books in the specialist collection.

Every book here is out of copyright; `license` and `license_basis` record why, so the list can be audited.
Texts come from the Internet Archive's OCR output. scripts/free_books.py downloads, chunks and uploads them;
this module holds the manifest and the pure text-handling so it can be tested without a network.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.rag.ingestion import Chunk, TxtIngestor

BATCH_ID = "free-books-2026-10"
COLLECTION_NOTE = "specialist_books"


@dataclass(frozen=True)
class BookSpec:
    id: str
    title: str
    author: str
    year: int
    domain: str                       # tarot | numerology | vastu | festivals | calendar | lore
    topic_tags: tuple[str, ...]
    archive_id: str                   # Internet Archive item
    archive_file: str                 # OCR text file inside the item
    license: str
    license_basis: str
    tradition: str = "vedic"
    start: str = ""                   # regex for the first line of the body
    start_occurrence: int = 1
    end: str = ""                     # regex for the first line after the body (index, errata, ...)
    strip: tuple[str, ...] = ()       # regexes for junk lines to delete (watermarks, page footers, ...)
    fixes: tuple[tuple[str, str], ...] = ()   # (regex, replacement) for systematic OCR mistakes in one scan
    keep_if: str = ""                 # keep only chunks that match at least `min_hits` distinct terms
    min_hits: int = 1

    @property
    def local_file(self) -> str:
        return f"{self.id}.txt"

    @property
    def source_url(self) -> str:
        return f"https://archive.org/details/{self.archive_id}"


_DIGITIZER = (
    r"^.*Digitized by.*$", r"^.*Original from.*$", r"^.*UNIVERSITY OF ILLINOIS.*$", r"^\s*URBANA-CHAMPAIGN.*$",
)

# Words that signal a Puranic passage the app can use: planets and the sky, lunar days and vratas, gems,
# house and temple building, and remedies. A chunk needs several different ones to be kept.
LORE_TERMS = (
    r"\b(planets?|nakshatras?|constellations?|zodiac|ascendant|horoscope|astrolog\w*|eclipses?|solstice|equinox|"
    r"tithis?|lunar days?|lunar mansions?|fortnight|muhurtas?|auspicious|inauspicious|"
    r"jupiter|saturn|mars|mercury|venus|rahu|ketu|"
    r"gems?|jewels?|rub(?:y|ies)|pearls?|coral|emeralds?|diamonds?|sapphires?|topaz|lapis|cat'?s[- ]eyes?|"
    r"vastu|foundations?|plots?|dwellings?|architect\w*|temples?|doors?|pillars?|"
    r"vratas?|fasts?|fasting|"
    r"remed\w+|expiat\w+|propitiat\w+)\b"
)

_PUBLIC_DOMAIN_OLD = "Public domain"

# First chapter heading that stands on its own line; chapter summaries in the contents pages never do.
_FIRST_CHAPTER = r"^\s*CHAPTER\s+[IVXLCDM]{1,8}\s*[\.,]?\s*$"

MANIFEST: tuple[BookSpec, ...] = (
    BookSpec(
        id="waite-pictorial-key-tarot",
        title="The Pictorial Key to the Tarot - A.E. Waite",
        author="Arthur Edward Waite", year=1911, domain="tarot", tradition="western",
        topic_tags=("tarot", "major-arcana", "minor-arcana", "divination", "spreads"),
        archive_id="A.EWaiteThePictorialKeyToTheTarot",
        archive_file="A. E Waite - The Pictorial Key to the Tarot_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1910/1911; author died 1942 (life+70 ended 2012; India life+60 ended 2002; US pre-1930). "
                      "Text taken from a plain capture of the sacred-texts.com transcription.",
        start=r"^\s*PART\s*I\s*$",
        strip=(r"^\s*http://www\.sacred-texts\.com/.*$", r"^\s*sacred-texts\b.*$", r"^\s*\d\.\d+\s+[A-Z].*$",
               r"^\s*Tarot Reading\s*$", r"^.*Buy CD-ROM.*$"),
    ),
    BookSpec(
        id="sepharial-kabala-of-numbers",
        title="The Kabala of Numbers - Sepharial",
        author="Sepharial (Walter Gorn Old)", year=1911, domain="numerology", tradition="western",
        topic_tags=("numerology", "kabala", "number-meanings", "name-numbers"),
        archive_id="1911-sephariel-kabala-of-numbers",
        archive_file="1911__sephariel___kabala_of_numbers_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1911 (William Rider & Son); author died 1929, so public domain in the US, UK and India. "
                      "Scan from the University of Illinois copy.",
        start=r"^\s*INTRODUCTION\s*$", start_occurrence=2, strip=_DIGITIZER,
    ),
    BookSpec(
        id="cheiro-book-of-numbers",
        title="Cheiro's Book of Numbers",
        author="Cheiro (William John Warner)", year=1926, domain="numerology", tradition="western",
        topic_tags=("numerology", "birth-numbers", "planetary-numbers", "name-numbers", "chaldean"),
        archive_id="in.ernet.dli.2015.70770",
        archive_file="2015.70770.Cheiros-Book-Of-Numbers_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="First published 1926 (Herbert Jenkins), now past the 95-year US term; author died 1936 "
                      "(UK life+70 ended 2006; India life+60 ended 1996). Digital Library of India scan of an early impression.",
        start=r"^\s*FOREWORD\s*$",
        fixes=((r"\bm\b", "in"), (r"\baU\b", "all")),   # this scan reads "in" as "m" and "all" as "aU"
    ),
    BookSpec(
        id="ramraz-architecture-of-the-hindus",
        title="Essay on the Architecture of the Hindus - Ram Raz",
        author="Ram Raz", year=1834, domain="vastu",
        topic_tags=("vastu", "architecture", "house-planning", "directions", "manasara", "temples"),
        archive_id="in.ernet.dli.2015.55600",
        archive_file="2015.55600.Essay-On-The-Architecture-Of-The-Hindus_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1834 by the Royal Asiatic Society; author died in the 1830s.",
        start=r"^\s*PREFACE\.?\s*$", end=r"^\s*ERRATA\.?\s*$",
    ),
    BookSpec(
        id="gupte-hindu-holidays-and-ceremonials",
        title="Hindu Holidays and Ceremonials - B.A. Gupte",
        author="Balkrishna Atmaram Gupte", year=1916, domain="festivals",
        topic_tags=("festivals", "holidays", "rituals", "folklore", "vratas", "calendar"),
        archive_id="hinduholidayscer00guptuoft",
        archive_file="hinduholidayscer00guptuoft_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1916 (Thacker, Spink, Calcutta): public domain in the US. The author was born in 1851, "
                      "so his death was long before 1964 and India's life+60 term has ended (inferred). "
                      "Internet Archive flags the scan NOT_IN_COPYRIGHT.",
        start=r"^\s*INTRODUCTION\s*$", end=r"^\s*INDEX\s*$",
    ),
    BookSpec(
        id="sewell-dikshit-the-indian-calendar",
        title="The Indian Calendar - Sewell and Dikshit",
        author="Robert Sewell and Sankara Balkrishna Dikshit", year=1896, domain="calendar",
        topic_tags=("calendar", "panchang", "tithi", "eras", "lunar-months", "conversion"),
        archive_id="indiancalendarwi00sewerich",
        archive_file="indiancalendarwi00sewerich_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1896; authors died 1925 and 1898. Internet Archive flags the scan NOT_IN_COPYRIGHT. "
                      "Numeric tables are dropped; only the explanatory text is kept.",
        start=r"^\s*PREFACE\.\s*$", end=r"^\s*INDEX\.\s*$",
    ),
    BookSpec(
        id="burgess-surya-siddhanta",
        title="Translation of the Surya-Siddhanta - Ebenezer Burgess",
        author="Ebenezer Burgess", year=1860, domain="calendar",
        topic_tags=("astronomy", "surya-siddhanta", "planetary-motion", "eclipses", "calendar"),
        archive_id="in.ernet.dli.2015.96668",
        archive_file="2015.96668.Translation-Of-The-Surya-siddhanta_djvu.txt",
        license=_PUBLIC_DOMAIN_OLD,
        license_basis="Published 1860; translator died 1870.",
    ),
    *(
        BookSpec(
            id=f"dutt-agni-purana-v{n}",
            title="Agni Purana - M.N. Dutt (translation)",
            author="Manmatha Nath Dutt (translator)", year=1903 if n == 1 else 1904, domain="lore",
            topic_tags=("purana", "vastu", "gems", "vratas", "jyotisha", "temples", "remedies"),
            archive_id=aid, archive_file=afile,
            license=_PUBLIC_DOMAIN_OLD,
            license_basis="Translation published 1903-04; translator died 1912. Some Internet Archive copies are 1987 "
                          "facsimile reprints; only the 1904 text is used, not the reprint front matter.",
            start=start, keep_if=LORE_TERMS, min_hits=2,
        )
        for n, aid, afile, start in (
            # Volume 1 already holds chapters 1-168 and volume 2 repeats 87-168 with noisier OCR, so volume 2
            # is read from chapter 169 only. Each volume starts at its first real chapter, skipping the contents.
            (1, "in.ernet.dli.2015.279469", "2015.279469.Agni-Puranam_djvu.txt", _FIRST_CHAPTER),
            (2, "in.ernet.dli.2015.33600", "2015.33600.Agni-Puranam--Vol-2_djvu.txt", r"^\s*CHAPTER\s+CLXIX\s*[\.,]?\s*$"),
            (3, "in.ernet.dli.2015.189132", "2015.189132.Agni-Puranam--Vol-3_djvu.txt", _FIRST_CHAPTER),
            (4, "in.ernet.dli.2015.189134", "2015.189134.Agni-Puranam--Vol-4_djvu.txt", _FIRST_CHAPTER),
        )
    ),
    *(
        BookSpec(
            id=f"dutt-garuda-purana-v{n}",
            title="Garuda Purana - M.N. Dutt (translation)",
            author="Manmatha Nath Dutt (translator)", year=1908, domain="lore",
            topic_tags=("purana", "gems", "jyotisha", "remedies", "vratas"),
            archive_id=aid, archive_file=afile,
            license=_PUBLIC_DOMAIN_OLD,
            license_basis="Translation published 1908; translator died 1912. Some copies are 1987 facsimile reprints.",
            start=_FIRST_CHAPTER, keep_if=LORE_TERMS, min_hits=2,
        )
        for n, aid, afile in (
            (1, "in.ernet.dli.2015.33648", "2015.33648.The-Garuda-Purana--Vol-1_djvu.txt"),
            (2, "in.ernet.dli.2015.189320", "2015.189320.The-Garuda-Purana--Vol-2_djvu.txt"),
        )
    ),
)

BY_ID = {b.id: b for b in MANIFEST}


# ── Text preparation ──────────────────────────────────────────────────────────

def prepare(raw: str, spec: BookSpec) -> str:
    """Trim to the body, drop junk lines, re-join hyphenated words and reflow paragraphs."""
    text = raw.replace("\r\n", "\n").replace("\x0c", "\n")

    if spec.start:
        matches = list(re.finditer(spec.start, text, flags=re.M))
        if len(matches) >= spec.start_occurrence:
            text = text[matches[spec.start_occurrence - 1].start():]
    if spec.end:
        m = re.search(spec.end, text, flags=re.M)
        if m:
            text = text[:m.start()]
    for pattern in spec.strip:
        # Remove the whole line, newline included, so a sentence that crosses a page break stays in one piece.
        text = re.sub(pattern + r"\n?", "", text, flags=re.M)
    for pattern, replacement in spec.fixes:
        text = re.sub(pattern, replacement, text)

    text = re.sub(r"(\w)-[ \t]*\n[ \t]*(\w)", r"\1\2", text)
    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s*\n\s*", " ", para)
        para = re.sub(r"[ \t]+", " ", para).strip()
        if para:
            paragraphs.append(para)
    return "\n\n".join(paragraphs)


def is_readable(chunk: str) -> bool:
    """Reject OCR noise and number tables: mostly letters, enough real words, not one repeated token."""
    visible = re.sub(r"\s", "", chunk)
    if not visible:
        return False
    if sum(c.isalpha() for c in visible) / len(visible) < 0.72:
        return False
    words = re.findall(r"[A-Za-z]{3,}", chunk)
    if len(words) < 15:
        return False
    return len(set(w.lower() for w in words)) / len(words) > 0.3


def _relevant(chunk: str, spec: BookSpec) -> bool:
    if not spec.keep_if:
        return True
    hits = {m.group(0).lower() for m in re.finditer(spec.keep_if, chunk, flags=re.I)}
    return len(hits) >= spec.min_hits


def chunk_book(spec: BookSpec, raw: str, seen: set[str] | None = None,
               chunk_size: int = 800, overlap: int = 150) -> tuple[list[Chunk], dict]:
    """Chunks ready for upload, plus counts of what was dropped and why.

    `seen` carries passage fingerprints between calls so volumes of one work do not upload the same text twice.
    """
    ingestor = TxtIngestor(chunk_size=chunk_size, chunk_overlap=overlap)
    body = prepare(raw, spec)
    pieces = [p for p in ingestor._chunk_text(body) if len(p) >= ingestor.min_chunk_size]

    stats = {"candidates": len(pieces), "unreadable": 0, "off_topic": 0, "duplicate": 0}
    seen = set() if seen is None else seen
    chunks: list[Chunk] = []
    for piece in pieces:
        if not is_readable(piece):
            stats["unreadable"] += 1
            continue
        if not _relevant(piece, spec):
            stats["off_topic"] += 1
            continue
        key = hashlib.sha1(re.sub(r"\W+", "", piece.lower())[:200].encode()).hexdigest()
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        index = len(chunks)
        meta = {
            "book": spec.title, "author": spec.author, "year": spec.year, "domain": spec.domain,
            "tradition": spec.tradition, "language": "eng", "topic_tags": list(spec.topic_tags),
            "license": spec.license, "source": spec.source_url, "source_file": spec.local_file,
            "batch_id": BATCH_ID, "chunk_index": index,
        }
        chunk_id = hashlib.sha256(f"{spec.id}:{index}:{piece[:100]}".encode()).hexdigest()[:16]
        chunks.append(Chunk(text=piece, metadata=meta, chunk_id=chunk_id))
    stats["kept"] = len(chunks)
    return chunks, stats
