"""
Ingest Vedic astrology PDF books into the vector store.

Handles:
  - Nested subfolders (recursively finds all PDFs)
  - Mixed languages: English, Sanskrit, Hindi, Marathi
  - Text PDFs (PyMuPDF fast path)
  - Scanned PDFs (pytesseract OCR fallback with language detection)
  - .docx files (python-docx)

Usage:
    python scripts/ingest_books.py --books-dir ./books
    python scripts/ingest_books.py --books-dir ./books --dry-run
    python scripts/ingest_books.py --books-dir ./books --skip-ocr
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import fitz  # PyMuPDF — used for fast page-count / scanned-PDF pre-check

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.ingestion import PDFIngestor
from app.rag.retrieval import HybridRetriever
from app.config import get_settings

# ── Language detection by folder / filename keywords ─────────────────────────
# Maps lowercase keyword → tesseract lang code
_LANG_HINTS: dict[str, str] = {
    "hindi":     "hin+eng",
    "tajika_nilakanthi_hindi": "hin+eng",
    "dasha_phal": "hin+eng",
    "sanket":    "hin+eng",
    "marathi":   "mar",
    "sanskrit":  "san",
    "nadi":      "san+eng",  # Nadi texts mix both
    "chandrakala": "san+eng",
    "bhrigu":    "san+eng",
    "saptarishi": "san+eng",
}

# Folder-level language overrides
_FOLDER_LANGS: dict[str, str] = {
    "ancient & classical jyotish texts": "eng+san",
    "classical sanskrit compendiums":    "san+eng",
    "dasha, timing & predictive texts":  "eng",
    "modern interpretative":             "eng",
    "nadi & special systems":            "san+eng",
    "nakshatra & yogas focused texts":   "eng",
}


def _detect_lang(path: Path) -> str:
    """Guess OCR language from folder name and filename."""
    folder = path.parent.name.lower()
    stem = path.stem.lower().replace("-", "_").replace(" ", "_")

    # Filename hints beat folder defaults (a Hindi book can sit in an
    # "eng" folder).
    for key, lang in _LANG_HINTS.items():
        if key in stem:
            return lang

    for key, lang in _FOLDER_LANGS.items():
        if key in folder:
            return lang

    return "eng"  # safe default


def _build_meta(path: Path) -> dict:
    """Build book metadata from file path."""
    folder = path.parent.name
    return {
        "book":        path.stem,
        "author":      "Unknown",
        "source_file": path.name,
        "folder":      folder,
        "topic_tags":  _folder_tag(folder),
        "language":    _detect_lang(path),
    }


def _folder_tag(folder: str) -> str:
    folder_lower = folder.lower()
    if "ancient" in folder_lower or "classical" in folder_lower:
        return "classical"
    if "dasha" in folder_lower or "timing" in folder_lower:
        return "timing"
    if "modern" in folder_lower:
        return "modern"
    if "nadi" in folder_lower:
        return "nadi"
    if "nakshatra" in folder_lower or "yoga" in folder_lower:
        return "nakshatra_yoga"
    return "general"


def _ingest_docx(path: Path, meta: dict) -> list:
    """Extract text from .docx and return fake Chunk objects."""
    try:
        import docx
        from app.rag.ingestion import Chunk
        import hashlib

        doc = docx.Document(str(path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if not text.strip():
            return []

        # Simple chunk by ~800 chars
        chunks = []
        words = text.split()
        buf = ""
        for word in words:
            if len(buf) + len(word) + 1 <= 800:
                buf += word + " "
            else:
                if buf.strip():
                    chunk_id = hashlib.sha256(
                        f"{meta['book']}:{len(chunks)}:{buf[:60]}".encode()
                    ).hexdigest()[:16]
                    chunks.append(Chunk(
                        text=buf.strip(),
                        metadata={**meta, "page": len(chunks) + 1},
                        chunk_id=chunk_id,
                    ))
                buf = word + " "
        if buf.strip():
            from app.rag.ingestion import Chunk
            import hashlib
            chunk_id = hashlib.sha256(
                f"{meta['book']}:{len(chunks)}:{buf[:60]}".encode()
            ).hexdigest()[:16]
            chunks.append(Chunk(
                text=buf.strip(),
                metadata={**meta, "page": len(chunks) + 1},
                chunk_id=chunk_id,
            ))
        return chunks
    except ImportError:
        print("  SKIP: python-docx not installed — pip install python-docx")
        return []
    except Exception as exc:
        print(f"  ERROR reading docx: {exc}")
        return []


def _make_qdrant(settings):
    """Qdrant client used only for the --skip-existing lookup."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PayloadSchemaType

    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=120,
    )
    try:
        client.create_payload_index(
            settings.books_collection, "book", PayloadSchemaType.KEYWORD
        )
    except Exception:
        pass  # index exists already; filtering still works without it
    return client


def _already_indexed(client, collection: str, book: str) -> bool:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    try:
        res = client.count(
            collection_name=collection,
            count_filter=Filter(
                must=[FieldCondition(key="book", match=MatchValue(value=book))]
            ),
            exact=True,
        )
        return res.count > 0
    except Exception as exc:
        print(f"   WARNING: could not check DB for '{book}': {exc}")
        return False


def main(
    books_dir: str,
    dry_run: bool = False,
    skip_ocr: bool = False,
    skip_existing: bool = False,
    exclude: list[str] | None = None,
) -> None:
    settings = get_settings()

    ingestor = PDFIngestor(chunk_size=800, chunk_overlap=150)
    retriever = HybridRetriever(
        embedding_model=settings.embedding_model,
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key,
        collection_name=settings.books_collection,
        embedding_dimension=settings.embedding_dimension,
        reranker_enabled=False,
    )

    qclient = _make_qdrant(settings) if skip_existing else None

    books_path = Path(books_dir)
    if not books_path.exists():
        print(f"ERROR: directory not found: {books_path}")
        sys.exit(1)

    # Recursively find all PDFs and docx files
    pdfs  = sorted(books_path.rglob("*.pdf"))
    docxs = sorted(books_path.rglob("*.docx"))
    all_files = pdfs + docxs

    if exclude:
        ex = [e.lower() for e in exclude]
        all_files = [
            f for f in all_files
            if not any(e in str(f.relative_to(books_path)).lower() for e in ex)
        ]

    if not all_files:
        print(f"No PDF or DOCX files found under {books_path}")
        return

    print(f"Found {len(all_files)} files ({len(pdfs)} PDFs + {len(docxs)} DOCX before --exclude)\n")

    total_chunks  = 0
    total_errors: list[str] = []
    skipped_ocr   = 0
    skipped_existing = 0

    for file_path in all_files:
        meta = _build_meta(file_path)
        rel  = file_path.relative_to(books_path)

        print(f"── {rel}")
        print(f"   lang={meta['language']}  folder_tag={meta['topic_tags']}")

        if qclient is not None and _already_indexed(
            qclient, settings.books_collection, str(meta["book"])
        ):
            print("   SKIP (already indexed)\n")
            skipped_existing += 1
            continue

        if dry_run:
            print("   [DRY RUN] would ingest\n")
            continue

        # ── DOCX ─────────────────────────────────────────────
        if file_path.suffix.lower() == ".docx":
            chunks = _ingest_docx(file_path, meta)
            if chunks:
                retriever.add_chunks(chunks)
                total_chunks += len(chunks)
                print(f"   chunks={len(chunks)} ✓\n")
            else:
                print(f"   WARNING: no text extracted\n")
            continue

        # ── PDF ───────────────────────────────────────────────
        # Quick page count check — skip obviously huge scanned books fast
        try:
            doc = fitz.open(str(file_path))
            page_count = len(doc)
            doc.close()
        except Exception as exc:
            print(f"   ERROR opening PDF: {exc}\n")
            total_errors.append(str(exc))
            continue

        if page_count > 50:
            # Quick sample — check first 3 pages for text
            try:
                doc = fitz.open(str(file_path))
                try:
                    sample_text = "".join(
                        doc[i].get_text() for i in range(min(3, page_count))
                    )
                finally:
                    doc.close()
            except Exception as exc:
                print(f"   ERROR sampling PDF: {exc}\n")
                total_errors.append(str(exc))
                continue

            if len(sample_text.strip()) < 100 and skip_ocr:
                print(f"   SKIP (scanned — no text in first 3 pages)\n")
                skipped_ocr += 1
                continue

        # Check if scanned (no OCR tag in filename)
        is_likely_scanned = "no ocr" in file_path.name.lower()
        if is_likely_scanned and skip_ocr:
            print(f"   SKIP (scanned, --skip-ocr)\n")
            skipped_ocr += 1
            continue

        result = ingestor.ingest(file_path, book_meta=meta, progress=True)

        print(f"   pages={result.pages_processed}  skipped={result.pages_skipped}  chunks={len(result.chunks)}")

        # If very few chunks extracted from a multi-page PDF → likely scanned
        pages_total = result.pages_processed + result.pages_skipped
        if pages_total > 5 and len(result.chunks) < 3:
            if skip_ocr:
                print(f"   SKIP (appears scanned, --skip-ocr set)\n")
                skipped_ocr += 1
                continue
            else:
                print(f"   NOTE: few chunks — may be scanned PDF, OCR will attempt")

        if result.errors:
            print(f"   ERRORS ({len(result.errors)}):")
            for e in result.errors[:3]:
                print(f"     - {e}")
            total_errors.extend(result.errors)

        if result.chunks:
            retriever.add_chunks(result.chunks)
            total_chunks += len(result.chunks)
            print(f"   indexed ✓\n")
        else:
            print(f"   WARNING: 0 chunks — may need OCR install or is pure image PDF\n")

    # ── Summary ───────────────────────────────────────────────
    print("=" * 50)
    print(f"Total chunks indexed : {total_chunks}")
    print(f"Total files          : {len(all_files)}")
    print(f"Skipped (no OCR)     : {skipped_ocr}")
    print(f"Skipped (already in DB): {skipped_existing}")
    if total_errors:
        print(f"Total errors         : {len(total_errors)}")
    print("\nDone!")
    print("\nTip: search the DB with:")
    print("  curl https://astrobrobackend-production.up.railway.app/api/books/list")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest Vedic astrology books (PDF + DOCX) into vector DB"
    )
    parser.add_argument("--books-dir", default="./books",
                        help="Root directory (subfolders scanned recursively)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List files without indexing")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="Skip files that appear scanned (no text extracted)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip books whose title is already in the vector DB")
    parser.add_argument("--exclude", action="append", default=[],
                        help="Skip files whose relative path contains this text (repeatable)")
    args = parser.parse_args()
    main(
        args.books_dir,
        dry_run=args.dry_run,
        skip_ocr=args.skip_ocr,
        skip_existing=args.skip_existing,
        exclude=args.exclude,
    )