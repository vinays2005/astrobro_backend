"""
PDF ingestion pipeline: extract → clean → chunk → metadata.

Data pipeline pattern:
  PDF file → text extraction → cleaning → semantic chunking → Chunk objects

Errors fail loud — no silent skips (all failures collected and returned).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Chunk:
    text: str
    metadata: dict[str, object]
    chunk_id: str


@dataclass
class IngestionResult:
    chunks: list[Chunk]
    errors: list[str]
    pages_processed: int
    pages_skipped: int


class PDFIngestor:
    """
    Ingest a single PDF into Chunk objects ready for vector indexing.

    Usage:
        ingestor = PDFIngestor()
        result = ingestor.ingest("books/bphs.pdf", book_meta={
            "book": "Brihat Parashara Hora Shastra",
            "author": "Parashara",
            "topic_tags": ["foundations", "houses", "planets"],
        })
        # result.chunks ready for HybridRetriever.add_chunks()
    """

    _ocr_warned: bool = False

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def ingest(
        self,
        pdf_path: str | Path,
        book_meta: dict[str, object],
        progress: bool = False,
    ) -> IngestionResult:
        """Full pipeline for one PDF. Returns chunks + per-page errors."""
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed: pip install pymupdf") from exc

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        doc = fitz.open(str(path))
        all_chunks: list[Chunk] = []
        errors: list[str] = []
        pages_skipped = 0

        ocr_lang = str(book_meta.get("language", "eng"))

        for page_num in range(len(doc)):
            if progress and page_num and page_num % 25 == 0:
                print(f"   ...page {page_num}/{len(doc)}", flush=True)
            try:
                page = doc[page_num]
                text: str = page.get_text("text")  # type: ignore[call-arg]

                if not text.strip():
                    text = self._ocr_page(page, ocr_lang)

                cleaned = self._clean_text(text)
                if len(cleaned) < 20:
                    pages_skipped += 1
                    continue

                for chunk_text in self._chunk_text(cleaned):
                    if len(chunk_text) < self.min_chunk_size:
                        continue
                    meta = {**book_meta, "page": page_num + 1, "source_file": str(path.name)}
                    all_chunks.append(Chunk(
                        text=chunk_text,
                        metadata=meta,
                        chunk_id=self._chunk_id(chunk_text, meta, len(all_chunks)),
                    ))
            except Exception as exc:
                errors.append(f"page {page_num + 1}: {exc}")
                pages_skipped += 1
        
        total_pages = len(doc)
        doc.close()
        return IngestionResult(
            chunks=all_chunks,
            errors=errors,
            pages_processed=total_pages - pages_skipped,
            pages_skipped=pages_skipped,
        )

    # ── Internal ──────────────────────────────────────────────

    def _ocr_page(self, page: object, lang: str = "eng") -> str:
        try:
            import io
            import os

            import pytesseract
            from PIL import Image

            cmd = os.environ.get("TESSERACT_CMD")
            if cmd:
                pytesseract.pytesseract.tesseract_cmd = cmd

            Image.MAX_IMAGE_PIXELS = None  # disable bomb check for large scans
            pix = page.get_pixmap(dpi=150)  # lower dpi = faster, less RAM
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                return str(pytesseract.image_to_string(img, lang=lang))
            except pytesseract.TesseractError:
                # Language pack not installed -> fall back to English.
                return str(pytesseract.image_to_string(img, lang="eng"))
        except Exception as exc:
            # Fail loud once per run instead of silently dropping every page.
            if not PDFIngestor._ocr_warned:
                PDFIngestor._ocr_warned = True
                print(f"   OCR WARNING (pages will come out empty): {exc}", flush=True)
            return ""

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\n\s*\d+\s*\n", "\n", text)  # standalone page numbers
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _chunk_text(self, text: str) -> list[str]:
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self.chunk_size:
                current = (current + "\n\n" + para).lstrip()
            else:
                if current:
                    chunks.append(current.strip())
                overlap = chunks[-1][-self.chunk_overlap:] if chunks and self.chunk_overlap > 0 else ""
                current = (overlap + "\n\n" + para).lstrip() if overlap else para

                # Para alone exceeds limit — split by sentence
                if len(current) > self.chunk_size * 1.5:
                    sentences = re.split(r"(?<=[.!?])\s+", current)
                    current = ""
                    for sent in sentences:
                        if len(current) + len(sent) + 1 <= self.chunk_size:
                            current = (current + " " + sent).strip()
                        else:
                            if current:
                                chunks.append(current.strip())
                            current = sent

        if current.strip():
            chunks.append(current.strip())

        return chunks

    def _chunk_id(self, text: str, meta: dict[str, object], index: int = 0) -> str:
        key = f"{meta.get('book','')}:{meta.get('page','')}:{index}:{text[:100]}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]