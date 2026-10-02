"""
Ingest pre-extracted TXT books into Qdrant.

Strategy:
  - Already indexed with good quality (>= 0.70)  → skip
  - Not indexed yet                               → upload
  - Already indexed but low quality (< 0.70)      → delete old chunks, upload fresh
  - We have a better TXT replacing a bad PDF scan → delete old PDF chunks, upload TXT

Usage:
    python scripts/ingest_txt_books.py --books-dir ./app/books
    python scripts/ingest_txt_books.py --books-dir ./app/books --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.rag.ingestion import TxtIngestor
from app.rag.retrieval import HybridRetriever
from app.config import get_settings

# ── Human-readable titles for each TXT file ───────────────────────────────────
BOOK_TITLES: dict[str, str] = {
    "ashtakavarga_prediction":        "Ashtakavarga System of Prediction",
    "bhavartha_ratnakara":            "Bhavartha Ratnakara",
    "bhrigu_nandi_nadi":              "Bhrigu Nandi Nadi",
    "brihat_jataka":                  "Brihat Jataka - Varahamihira",
    "brihat_parashara_hora_shastra":  "Brihat Parashara Hora Shastra",
    "chamatkar_chintamani":           "Chamatkar Chintamani",
    "chandra_kala_nadi":              "Chandra Kala Nadi",
    "christian_astrology":            "Christian Astrology - William Lilly",
    "deva_keralam":                   "Deva Keralam",
    "dhruva_nadi":                    "Dhruva Nadi",
    "divisional_charts":              "Divisional Charts",
    "graha_laghava":                  "Graha Laghava",
    "hellenistic_astrology_brennan":  "Hellenistic Astrology - Chris Brennan",
    "hora_sara":                      "Hora Sara",
    "how_to_judge_horoscope":         "How to Judge a Horoscope - B.V. Raman",
    "jaimini_astrology":              "Jaimini Astrology - Sanjay Rath",
    "jaimini_sutras":                 "Jaimini Sutras",
    "jataka_bharanam":                "Jataka Bharanam",
    "jataka_parijata":                "Jataka Parijata",
    "jataka_tattva":                  "Jataka Tattva",
    "kp_astrology":                   "KP Astrology",
    "laghu_parashari":                "Laghu Parashari",
    "lal_kitab":                      "Lal Kitab",
    "muhurta_chintamani":             "Muhurta Chintamani",
    "muhurta_martanda":               "Muhurta Martanda",
    "nakshatra_paddhati":             "Nakshatra Paddhati",
    "phaladeepika":                   "Phaladeepika",
    "predicting_navamsa":             "Predicting Through Navamsa",
    "predictive_astrology_raman":     "Predictive Astrology - B.V. Raman",
    "rahu_ketu_mysteries":            "Rahu and Ketu Mysteries",
    "sanketa_nidhi":                  "Sanketa Nidhi",
    "saravali":                       "Saravali - Kalyanvarma",
    "sarvartha_chintamani":           "Sarvartha Chintamani",
    "shatpanchasika":                 "Shatpanchasika",
    "tajika_neelakanthi":             "Tajika Neelakanthi",
    "tetrabiblos":                    "Tetrabiblos - Ptolemy",
    "three_hundred_combinations":     "Three Hundred Important Combinations",
    "transit_predictions":            "Transit Predictions - Gochara",
    "uttara_kalamrita":               "Uttara Kalamrita",
    "vipareeta_raja_yoga":            "Vipareeta Raja Yoga - Sanjay Rath",
}

# Old PDF-indexed titles to delete before re-uploading from TXT
# (only entries where the old version has low quality)
REPLACE_OLD: dict[str, list[str]] = {
    "brihat_parashara_hora_shastra": [
        "Brihat Parasara Hora Sastra with English Translation Girish Chand Sharma Volume 1",
        "hora shastra (varahamihira)",
    ],
    "chamatkar_chintamani": [
        "Chamatkar Chintamani - Braj Bihari Lal Sharma",
    ],
    "brihat_jataka": [
        "brihat jataka (varahamihira)",
    ],
    "jataka_parijata": [
        "Jataka-Parijata",
    ],
    "laghu_parashari": [
        "Laghu parashari S R Jha",
    ],
    "tajika_neelakanthi": [
        "tajika_nilakanthi_hindi",
    ],
}

QUALITY_THRESHOLD = 0.70


def _quality_score(text: str) -> float:
    if not text or len(text.strip()) < 50:
        return 0.0
    t = text[:2000]
    alpha = sum(1 for c in t if c.isalpha())
    total = len(t)
    ar = alpha / total
    words = re.findall(r"[a-zA-Z]{3,}", t)
    if not words:
        return 0.0
    avg_wl = sum(len(w) for w in words) / len(words)
    wl_ok = 1.0 if 4 <= avg_wl <= 9 else 0.5
    return round(ar * wl_ok, 3)


def _txt_quality(path: Path) -> float:
    """Sample 3 positions in the TXT and average quality score."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) < 500:
        return 0.0
    positions = [0, len(text) // 3, 2 * len(text) // 3]
    scores = [_quality_score(text[p:p + 3000]) for p in positions]
    return round(sum(scores) / len(scores), 3)


def _get_indexed_books(qdrant_url: str, qdrant_api_key: str, collection: str) -> dict[str, int]:
    """Return {book_title: chunk_count} for all currently indexed books."""
    import requests
    resp = requests.get(
        "https://astrobrobackend-production.up.railway.app/api/books/list",
        timeout=20,
    )
    data = resp.json()
    return {b["title"]: b["chunks"] for b in data.get("books", [])}


def _sample_quality(client, collection: str, book_title: str) -> float:
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        res = client.scroll(
            collection_name=collection,
            with_payload=True,
            with_vectors=False,
            limit=5,
            scroll_filter=Filter(
                must=[FieldCondition(key="book", match=MatchValue(value=book_title))]
            ),
        )
        pts = res[0]
        if not pts:
            return 0.0
        scores = [_quality_score(p.payload.get("text", "")) for p in pts]
        return sum(scores) / len(scores) if scores else 0.0
    except Exception:
        return 0.0


def _delete_book(client, collection: str, book_title: str) -> int:
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[FieldCondition(key="book", match=MatchValue(value=book_title))]
            ),
            wait=True,
        )
        return 1
    except Exception as e:
        print(f"   WARNING: could not delete '{book_title}': {e}")
        return 0


def main(books_dir: str, dry_run: bool = False) -> None:
    settings = get_settings()

    from qdrant_client import QdrantClient
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=120,
    )

    indexed = _get_indexed_books(settings.qdrant_url, settings.qdrant_api_key, settings.books_collection)
    print(f"Currently indexed: {len(indexed)} books, {sum(indexed.values())} chunks\n")

    ingestor = TxtIngestor(chunk_size=800, chunk_overlap=150)
    retriever = HybridRetriever(
        embedding_model=settings.embedding_model,
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key,
        collection_name=settings.books_collection,
        embedding_dimension=settings.embedding_dimension,
        reranker_enabled=False,
    )

    books_path = Path(books_dir)
    txt_files = sorted(f for f in books_path.glob("*.txt"))
    print(f"Found {len(txt_files)} TXT files in {books_path}\n")

    stats = {"uploaded": 0, "skipped": 0, "replaced": 0, "low_txt": 0, "errors": 0}

    for txt_path in txt_files:
        stem = txt_path.stem
        title = BOOK_TITLES.get(stem, stem)
        txt_score = _txt_quality(txt_path)
        size_kb = txt_path.stat().st_size // 1024

        print(f"-- {title}  ({size_kb} KB, txt_quality={txt_score:.2f})")

        if txt_score < 0.55:
            print(f"   SKIP — TXT file itself has low quality ({txt_score:.2f}), not worth uploading\n")
            stats["low_txt"] += 1
            continue

        # Check if already indexed under the human-readable title
        already_score = None
        if title in indexed:
            already_score = _sample_quality(qdrant, settings.books_collection, title)
            if already_score >= QUALITY_THRESHOLD:
                print(f"   SKIP — already indexed with good quality ({already_score:.2f})\n")
                stats["skipped"] += 1
                continue
            else:
                print(f"   Already indexed but LOW quality ({already_score:.2f}) — will replace")

        # Delete old PDF-indexed versions if we have a better TXT replacement
        old_titles = REPLACE_OLD.get(stem, [])
        for old_title in old_titles:
            if old_title in indexed:
                old_score = _sample_quality(qdrant, settings.books_collection, old_title)
                if old_score < QUALITY_THRESHOLD:
                    print(f"   Deleting old low-quality entry: '{old_title}' (score={old_score:.2f})")
                    if not dry_run:
                        _delete_book(qdrant, settings.books_collection, old_title)
                else:
                    print(f"   Keeping old entry '{old_title}' — quality OK ({old_score:.2f})")

        # Delete our own previous upload if re-uploading
        if already_score is not None and title in indexed:
            print(f"   Deleting previous '{title}' chunks for re-upload")
            if not dry_run:
                _delete_book(qdrant, settings.books_collection, title)

        if dry_run:
            print(f"   [DRY RUN] would upload '{title}'\n")
            continue

        # Ingest and upload
        try:
            meta = {
                "book":     title,
                "stem":     stem,
                "source":   "archive.org TXT",
                "format":   "txt",
            }
            result = ingestor.ingest(txt_path, book_meta=meta)
            if not result.chunks:
                print(f"   WARNING: 0 chunks produced — skipping\n")
                stats["errors"] += 1
                continue

            retriever.add_chunks(result.chunks)
            action = "replaced" if (already_score is not None or old_titles) else "uploaded"
            print(f"   {action.upper()} — {len(result.chunks)} chunks\n")
            if action == "replaced":
                stats["replaced"] += 1
            else:
                stats["uploaded"] += 1
        except Exception as exc:
            print(f"   ERROR: {exc}\n")
            stats["errors"] += 1

    print("=" * 55)
    print(f"New uploads   : {stats['uploaded']}")
    print(f"Replaced      : {stats['replaced']}")
    print(f"Skipped (good): {stats['skipped']}")
    print(f"Skipped (low TXT): {stats['low_txt']}")
    print(f"Errors        : {stats['errors']}")
    print("\nVerify with:")
    print("  curl https://astrobrobackend-production.up.railway.app/api/books/list")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--books-dir", default="./app/books")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.books_dir, dry_run=args.dry_run)
