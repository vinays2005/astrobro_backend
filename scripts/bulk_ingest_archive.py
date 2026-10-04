"""
Bulk Archive.org → Qdrant ingestion pipeline.

Searches Archive.org for Vedic/Hindu/Jyotish astrology texts, downloads PDFs,
extracts text (with OCR fallback), chunks, and indexes to Qdrant.

Usage (venv311 active):
    python scripts/bulk_ingest_archive.py [--limit 500] [--out-dir C:/path/to/books] [--no-ocr]
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io as _io
sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(".env")

MAX_PDF_MB   = 80   # skip files larger than this
MIN_PDF_KB   = 20   # skip tiny/corrupt files
BATCH_SIZE   = 32   # Qdrant upload batch
DPI          = 150  # OCR resolution

# ── Archive.org search queries ────────────────────────────────────────────────
# Organized by topic: Love, Career, Money, Marriage, Family, Travel + foundational
SEARCH_QUERIES = [
    # ── Foundational texts ────────────────────────────────────────────────────
    'subject:"Hindu astrology" AND mediatype:texts',
    'subject:"Vedic astrology" AND mediatype:texts',
    'subject:"Jyotish" AND mediatype:texts',
    'subject:"Astrology, Hindu" AND mediatype:texts',
    'subject:"Hindu Predictive Astrology" AND mediatype:texts',
    'subject:"Jyotisha" AND mediatype:texts',
    'subject:"Indian astrology" AND mediatype:texts',
    'subject:"Astrological prediction" AND mediatype:texts language:English',
    'title:"vedic astrology" AND mediatype:texts',
    'title:"hindu astrology" AND mediatype:texts',
    'title:"jyotish" AND mediatype:texts',
    'title:"brihat parashara" AND mediatype:texts',
    'title:"phaladeepika" AND mediatype:texts',
    'title:"saravali" AND mediatype:texts',
    'title:"brihat jataka" AND mediatype:texts',
    'title:"jataka parijata" AND mediatype:texts',
    'title:"hora sara" AND mediatype:texts',
    'title:"uttara kalamrita" AND mediatype:texts',
    'title:"laghu parashari" AND mediatype:texts',
    'title:"sarvartha chintamani" AND mediatype:texts',
    'title:"jataka tattwa" AND mediatype:texts',
    'title:"bhavartha ratnakara" AND mediatype:texts',

    # ── LOVE / ROMANCE ────────────────────────────────────────────────────────
    'title:"love" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"love marriage" AND subject:"astrology" AND mediatype:texts',
    'title:"romance" AND subject:"astrology" AND mediatype:texts',
    'title:"venus" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"seventh house" AND subject:"astrology" AND mediatype:texts',
    'title:"fifth house" AND subject:"astrology" AND mediatype:texts',
    'title:"partner" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"relationship" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"compatibility" AND subject:"astrology" AND mediatype:texts',
    'title:"synastry" AND subject:"astrology" AND mediatype:texts',

    # ── CAREER / PROFESSION ───────────────────────────────────────────────────
    'title:"career" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"profession" AND subject:"astrology" AND mediatype:texts',
    'title:"tenth house" AND subject:"astrology" AND mediatype:texts',
    'title:"vocation" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"success" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"how to judge a horoscope" AND mediatype:texts',
    'title:"notable horoscopes" AND mediatype:texts',
    'title:"notable horoscopes" AND creator:"Raman" AND mediatype:texts',
    'title:"planets" AND subject:"profession" AND mediatype:texts',
    'title:"business" AND subject:"Hindu astrology" AND mediatype:texts',

    # ── MONEY / WEALTH / FINANCE ──────────────────────────────────────────────
    'title:"wealth" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"money" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"financial astrology" AND mediatype:texts',
    'title:"dhana yoga" AND mediatype:texts',
    'title:"second house" AND subject:"astrology" AND mediatype:texts',
    'title:"eleventh house" AND subject:"astrology" AND mediatype:texts',
    'title:"ashtakavarga" AND mediatype:texts',
    'title:"dasa system" AND mediatype:texts',
    'title:"varshaphal" AND mediatype:texts',
    'title:"planetary influences" AND subject:"astrology" AND mediatype:texts',
    'title:"three hundred important combinations" AND mediatype:texts',

    # ── MARRIAGE / TIMING ─────────────────────────────────────────────────────
    'title:"marriage" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"marriage" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"married life" AND subject:"astrology" AND mediatype:texts',
    'title:"when will i get married" AND mediatype:texts',
    'title:"spouse" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"muhurtha" AND mediatype:texts',
    'title:"muhurta" AND mediatype:texts',
    'title:"electional astrology" AND mediatype:texts',
    'title:"jaimini" AND mediatype:texts',
    'title:"darakaraka" AND mediatype:texts',
    'title:"navamsa" AND mediatype:texts',
    'title:"upapada" AND mediatype:texts',

    # ── FAMILY / CHILDREN ─────────────────────────────────────────────────────
    'title:"children" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"family" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"fifth house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"fourth house" AND subject:"astrology" AND mediatype:texts',
    'title:"progeny" AND subject:"astrology" AND mediatype:texts',
    'title:"parent" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"mother" AND subject:"astrology" AND mediatype:texts',
    'title:"father" AND subject:"astrology" AND mediatype:texts',
    'title:"medical astrology" AND mediatype:texts',

    # ── TRAVEL / FOREIGN ──────────────────────────────────────────────────────
    'title:"travel" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"foreign" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"journey" AND subject:"astrology" AND mediatype:texts',
    'title:"twelfth house" AND subject:"astrology" AND mediatype:texts',
    'title:"abroad" AND subject:"astrology" AND mediatype:texts',
    'title:"tajika" AND mediatype:texts',
    'title:"prashna" AND mediatype:texts',
    'title:"horary astrology" AND mediatype:texts',
    'title:"prasna marga" AND mediatype:texts',

    # ── Top authors (cover all topics) ────────────────────────────────────────
    'creator:"B.V. Raman" AND mediatype:texts',
    'creator:"B.V.Raman" AND mediatype:texts',
    'creator:"Bangalore Venkata Raman" AND mediatype:texts',
    'creator:"K.N. Rao" AND mediatype:texts',
    'creator:"Sanjay Rath" AND mediatype:texts',
    'creator:"Hart de Fouw" AND mediatype:texts',
    'creator:"Robert Svoboda" AND mediatype:texts',
    'creator:"David Frawley" AND mediatype:texts',
    'creator:"Bepin Behari" AND mediatype:texts',
    'creator:"Mantreswara" AND mediatype:texts',
    'creator:"Varahamihira" AND mediatype:texts',
    'creator:"Parashara" AND mediatype:texts',
    'creator:"Krishnamurti" AND subject:"astrology" AND mediatype:texts',
    'creator:"V.K. Choudhry" AND mediatype:texts',
    'creator:"Shakti Mohan Singh" AND mediatype:texts',
    'creator:"Nathalia" AND subject:"astrology" AND mediatype:texts',

    # ── Techniques (used for all topic predictions) ───────────────────────────
    'title:"nakshatra" AND mediatype:texts',
    'title:"dasha" AND subject:"astrology" AND mediatype:texts',
    'title:"yoga" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"shadbala" AND mediatype:texts',
    'title:"nadi astrology" AND mediatype:texts',
    'title:"divisional chart" AND mediatype:texts',
    'title:"kp astrology" AND mediatype:texts',
    'title:"horoscope" AND subject:"Hindu" AND mediatype:texts',
    'title:"graha" AND subject:"astrology" AND mediatype:texts',
    'title:"rahu" AND subject:"astrology" AND mediatype:texts',
    'title:"saturn" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"remedies" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"transit" AND subject:"Hindu astrology" AND mediatype:texts',
    'subject:"Astrology" AND language:"Sanskrit" AND mediatype:texts',
    'subject:"Hindu astronomy" AND mediatype:texts',
    'title:"panchang" AND mediatype:texts',
    'title:"lagna" AND subject:"astrology" AND mediatype:texts',

    # ── TRAVEL / FOREIGN (expanded — target weak category) ───────────────────
    'title:"foreign travel" AND mediatype:texts',
    'title:"foreign settlement" AND subject:"astrology" AND mediatype:texts',
    'title:"abroad" AND subject:"vedic astrology" AND mediatype:texts',
    'title:"overseas" AND subject:"astrology" AND mediatype:texts',
    'title:"twelfth house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"12th house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"foreign lands" AND subject:"astrology" AND mediatype:texts',
    'title:"foreign connection" AND subject:"astrology" AND mediatype:texts',
    'title:"rahu" AND subject:"vedic astrology" AND mediatype:texts',
    'title:"ketu" AND subject:"vedic astrology" AND mediatype:texts',
    'title:"rahu ketu" AND subject:"astrology" AND mediatype:texts',
    'title:"nodes" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"tajika" AND subject:"astrology" AND mediatype:texts',
    'title:"annual horoscope" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"prasna astrology" AND mediatype:texts',
    'title:"horary" AND subject:"Hindu" AND mediatype:texts',
    'subject:"Travel" AND subject:"astrology" AND mediatype:texts',
    'title:"journey" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"immigration" AND subject:"astrology" AND mediatype:texts',
    'title:"relocation" AND subject:"astrology" AND mediatype:texts',
    'title:"foreign country" AND subject:"astrology" AND mediatype:texts',
    'title:"foreign nationals" AND subject:"astrology" AND mediatype:texts',
    'creator:"K.S. Krishnamurti" AND mediatype:texts',
    'title:"KP astrology foreign" AND mediatype:texts',
    'title:"ninth house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"ninth house" AND subject:"astrology" AND mediatype:texts',
    'title:"moon rahu" AND subject:"astrology" AND mediatype:texts',
    'title:"foreign" AND subject:"Jyotish" AND mediatype:texts',
    'title:"transit" AND subject:"vedic astrology" AND mediatype:texts',
    'title:"transit" AND subject:"Hindu" AND mediatype:texts',

    # ── RELATIONSHIP / INTIMACY (expanded — target weak category) ────────────
    'title:"8th house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"eighth house" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"venus" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"kama" AND subject:"astrology" AND mediatype:texts',
    'title:"desire" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"attraction" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"soulmate" AND subject:"astrology" AND mediatype:texts',
    'title:"nakshatra compatibility" AND mediatype:texts',
    'title:"nakshatra matching" AND mediatype:texts',
    'title:"ashtakoota" AND mediatype:texts',
    'title:"guna milan" AND mediatype:texts',
    'title:"kundali matching" AND mediatype:texts',
    'title:"horoscope matching" AND mediatype:texts',
    'title:"romantic" AND subject:"astrology" AND mediatype:texts',
    'title:"secret" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"intimate" AND subject:"astrology" AND mediatype:texts',
    'title:"sexual" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"sensual" AND subject:"astrology" AND mediatype:texts',
    'title:"lover" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"passion" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"hidden" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"occult" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"synastry" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"composite" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"relationship astrology" AND mediatype:texts',
    'title:"love marriage" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"intercaste marriage" AND subject:"astrology" AND mediatype:texts',
    'title:"extra marital" AND subject:"astrology" AND mediatype:texts',
    'title:"shukra" AND subject:"astrology" AND mediatype:texts',
    'title:"libido" AND subject:"astrology" AND mediatype:texts',
    'title:"scorpio" AND subject:"relationship" AND mediatype:texts',

    # ── REMEDIES (1000 books target) ─────────────────────────────────────────
    'title:"remedies" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"remedy" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"upaya" AND subject:"astrology" AND mediatype:texts',
    'title:"upaya" AND mediatype:texts',
    'title:"mantra" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"mantra" AND subject:"astrology" AND mediatype:texts',
    'title:"gemstone" AND subject:"astrology" AND mediatype:texts',
    'title:"gem therapy" AND mediatype:texts',
    'title:"ratna" AND subject:"astrology" AND mediatype:texts',
    'title:"navratna" AND mediatype:texts',
    'title:"rudraksha" AND mediatype:texts',
    'title:"yantra" AND subject:"astrology" AND mediatype:texts',
    'title:"yantra" AND subject:"Hindu" AND mediatype:texts',
    'title:"yantra mantra" AND mediatype:texts',
    'title:"graha shanti" AND mediatype:texts',
    'title:"navagraha" AND subject:"astrology" AND mediatype:texts',
    'title:"navagraha" AND mediatype:texts',
    'title:"navagraha remedies" AND mediatype:texts',
    'title:"puja" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"charity" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"daana" AND subject:"astrology" AND mediatype:texts',
    'title:"daana" AND subject:"Hindu" AND mediatype:texts',
    'subject:"Lal Kitab" AND mediatype:texts',
    'title:"lal kitab" AND mediatype:texts',
    'title:"lal kitab remedies" AND mediatype:texts',
    'title:"mantra shastra" AND mediatype:texts',
    'title:"beej mantra" AND mediatype:texts',
    'title:"vedic mantra" AND subject:"astrology" AND mediatype:texts',
    'title:"planetary remedies" AND mediatype:texts',
    'title:"astrological remedies" AND mediatype:texts',
    'title:"jyotish remedies" AND mediatype:texts',
    'title:"jyotish upaya" AND mediatype:texts',
    'title:"rahu ketu remedies" AND mediatype:texts',
    'title:"saturn remedies" AND mediatype:texts',
    'title:"shani remedies" AND mediatype:texts',
    'title:"shani" AND subject:"remedy" AND mediatype:texts',
    'title:"kalsarpa" AND mediatype:texts',
    'title:"kalsarpa dosh" AND mediatype:texts',
    'title:"kalsarpa yoga remedies" AND mediatype:texts',
    'title:"mangal dosha" AND mediatype:texts',
    'title:"manglik" AND subject:"astrology" AND mediatype:texts',
    'title:"mangal dosha remedies" AND mediatype:texts',
    'title:"dosha" AND subject:"Vedic astrology" AND mediatype:texts',
    'title:"shanti" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"parihar" AND subject:"astrology" AND mediatype:texts',
    'title:"kavach" AND subject:"astrology" AND mediatype:texts',
    'subject:"Gemstones" AND subject:"astrology" AND mediatype:texts',
    'subject:"Mantra" AND subject:"Hindu" AND mediatype:texts',
    'title:"yantra mantra tantra" AND mediatype:texts',
    'title:"tantra" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"amulet" AND subject:"astrology" AND mediatype:texts',
    'title:"talisman" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"mahadasha remedies" AND mediatype:texts',
    'title:"dasha remedies" AND mediatype:texts',
    'title:"nakshatra remedies" AND mediatype:texts',
    'title:"vedic remedies" AND mediatype:texts',
    'title:"japa" AND subject:"Hindu" AND mediatype:texts',
    'title:"stotra" AND subject:"astrology" AND mediatype:texts',
    'title:"ashtottara" AND mediatype:texts',
    'title:"graha" AND title:"remedy" AND mediatype:texts',
    'title:"sun remedy" AND mediatype:texts',
    'title:"moon remedy" AND mediatype:texts',
    'title:"mars remedy" AND mediatype:texts',
    'title:"mercury remedy" AND mediatype:texts',
    'title:"jupiter remedy" AND mediatype:texts',
    'title:"venus remedy" AND mediatype:texts',
    'title:"rahu remedy" AND mediatype:texts',
    'title:"ketu remedy" AND mediatype:texts',
    'title:"spiritual remedy" AND subject:"astrology" AND mediatype:texts',
    'title:"fasting" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"vrat" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"upasana" AND subject:"Hindu" AND mediatype:texts',
    'title:"devotion" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"prayaschitta" AND mediatype:texts',
    'title:"atonement" AND subject:"Hindu astrology" AND mediatype:texts',
    'subject:"Hindu rituals" AND mediatype:texts',
    'subject:"Jyotish remedies" AND mediatype:texts',
    'creator:"G.S. Kapoor" AND mediatype:texts',
    'creator:"Shanker Adawal" AND mediatype:texts',
    'creator:"V.K. Choudhry" AND subject:"remedy" AND mediatype:texts',
    'creator:"K.N. Rao" AND subject:"remedy" AND mediatype:texts',
    'title:"krishna" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"vishnu" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"shiva" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"lakshmi" AND subject:"astrology" AND mediatype:texts',
    'title:"hanuman" AND subject:"astrology" AND mediatype:texts',
    'title:"ganesh" AND subject:"astrology" AND mediatype:texts',
    'title:"sudarshana" AND subject:"astrology" AND mediatype:texts',
    'title:"remedial measures" AND mediatype:texts',
    'title:"remedial" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"practical remedies" AND subject:"astrology" AND mediatype:texts',
    'title:"gems" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"diamond" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"ruby" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"emerald" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"blue sapphire" AND subject:"astrology" AND mediatype:texts',
    'title:"yellow sapphire" AND subject:"astrology" AND mediatype:texts',
    'title:"red coral" AND subject:"astrology" AND mediatype:texts',
    'title:"pearl" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"cat eye" AND subject:"astrology" AND mediatype:texts',
    'title:"hessonite" AND subject:"astrology" AND mediatype:texts',
    'title:"protective mantra" AND mediatype:texts',
    'title:"healing mantra" AND mediatype:texts',
    'title:"saturn worship" AND mediatype:texts',
    'title:"rahu worship" AND mediatype:texts',
    'title:"sun worship" AND mediatype:texts',
    'title:"planetary worship" AND mediatype:texts',
    'title:"vishnu sahasranam" AND mediatype:texts',
    'title:"mahamrityunjaya" AND mediatype:texts',
    'title:"gayatri" AND subject:"astrology" AND mediatype:texts',
    'title:"durga" AND subject:"Hindu astrology" AND mediatype:texts',
    'title:"saraswati" AND subject:"Hindu astrology" AND mediatype:texts',
]

# ── Already-indexed books (skip re-ingestion) — loaded at runtime ─────────────
_INDEXED_TITLES: set[str] = set()

def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _fetch_json(url: str) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  FETCH_ERR {url[:80]}: {e}", flush=True)
        return None

def search_archive(query: str, rows: int = 200) -> list[dict]:
    """Return list of Archive.org items matching query."""
    params = urllib.parse.urlencode({
        "q": query,
        "fl[]": "identifier,title,creator,subject,mediatype",
        "rows": rows,
        "output": "json",
    })
    url = f"https://archive.org/advancedsearch.php?{params}"
    data = _fetch_json(url)
    if not data:
        return []
    return data.get("response", {}).get("docs", [])

def get_best_pdf(identifier: str) -> tuple[str, str] | None:
    """Return (download_url, filename) for best PDF in an Archive.org item."""
    url = f"https://archive.org/metadata/{identifier}/files"
    data = _fetch_json(url)
    if not data:
        return None
    files = data.get("result", [])
    pdfs = [f for f in files if str(f.get("name", "")).lower().endswith(".pdf")]
    if not pdfs:
        # Try txt files
        txts = [f for f in files if str(f.get("name", "")).lower().endswith(".txt")]
        if txts:
            best = sorted(txts, key=lambda x: int(x.get("size", 0)), reverse=True)[0]
            fname = best["name"]
            return (f"https://archive.org/download/{identifier}/{urllib.parse.quote(fname)}", fname)
        return None
    # Pick the smallest PDF under MAX_PDF_MB
    valid = [f for f in pdfs if int(f.get("size", 0)) < MAX_PDF_MB * 1024 * 1024
             and int(f.get("size", 0)) > MIN_PDF_KB * 1024]
    if not valid:
        return None
    best = sorted(valid, key=lambda x: int(x.get("size", 0)))[0]
    fname = best["name"]
    return (f"https://archive.org/download/{identifier}/{urllib.parse.quote(fname)}", fname)

def download_file(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180, context=_ssl_ctx()) as r, open(dest, "wb") as f:
            f.write(r.read())
        if dest.stat().st_size < MIN_PDF_KB * 1024:
            dest.unlink()
            print("  DL_FAIL: file too small", flush=True)
            return False
        # Verify it's a real PDF, not an HTML access-denied page
        if dest.suffix.lower() == ".pdf":
            with open(dest, "rb") as f:
                magic = f.read(5)
            if magic != b"%PDF-":
                dest.unlink()
                print("  DL_FAIL: not a PDF (restricted/CDL-only on Archive.org)", flush=True)
                return False
        return True
    except Exception as e:
        if dest.exists():
            dest.unlink()
        print(f"  DL_FAIL: {e}", flush=True)
        return False

def extract_text_pdf(path: Path, skip_ocr: bool = False) -> str:
    import fitz
    doc = fitz.open(str(path))
    parts = []
    for page in doc:
        text = page.get_text("text").strip()
        if not text and not skip_ocr:
            try:
                import pytesseract
                from PIL import Image
                pix = page.get_pixmap(dpi=DPI)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img, lang="eng").strip()
            except Exception:
                pass
        if text.strip():
            parts.append(text.strip())
    doc.close()
    return "\n\n".join(parts)

def chunk_text(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i:i + size])
        if len(chunk) >= 100:
            chunks.append(chunk)
        i += size - overlap
    return chunks

def ingest_chunks(chunks: list[str], meta: dict, retriever) -> int:
    import hashlib, uuid, numpy as np
    from qdrant_client.models import PointStruct

    texts = chunks
    # fastembed.TextEmbedding.embed() returns a generator of numpy arrays;
    # SentenceTransformer.encode() returns a 2-D ndarray — support both.
    raw = retriever._embedder.embed(texts) if hasattr(retriever._embedder, "embed") \
          else retriever._embedder.encode(texts, normalize_embeddings=True)
    emb_list = [e.tolist() if hasattr(e, "tolist") else list(e) for e in raw]
    embeddings = emb_list

    points = []
    for j, (emb, txt) in enumerate(zip(embeddings, texts)):
        raw_id = hashlib.sha256(f"{meta['book']}::{j}::{txt[:40]}".encode()).hexdigest()[:16]
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))
        points.append(PointStruct(id=point_id, vector=list(emb), payload={**meta, "text": txt}))

    for i in range(0, len(points), BATCH_SIZE):
        retriever._qdrant.upsert(
            collection_name=retriever._collection_name,
            points=points[i:i + BATCH_SIZE],
        )
    return len(points)

def load_indexed_titles(retriever) -> set[str]:
    titles: set[str] = set()
    offset = None
    try:
        while True:
            pts, offset = retriever._qdrant.scroll(
                collection_name=retriever._collection_name,
                limit=500, offset=offset,
                with_payload=["book"], with_vectors=False,
            )
            for p in pts:
                t = str((p.payload or {}).get("book", ""))
                if t:
                    titles.add(t.lower().strip())
            if offset is None:
                break
    except Exception:
        pass
    return titles

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000, help="Max books to process")
    parser.add_argument("--out-dir", default=r"C:\CODE\astrobro app\main app\astro_books\books")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--skip-download", action="store_true", help="Skip download, only ingest existing files")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "staging"
    staging.mkdir(exist_ok=True)

    print("Loading retriever...", flush=True)
    from app.rag.retrieval import HybridRetriever
    from app.config import get_settings
    s = get_settings()
    retriever = HybridRetriever(
        embedding_model=s.embedding_model,
        qdrant_url=s.qdrant_url,
        qdrant_api_key=s.qdrant_api_key,
        collection_name=s.books_collection,
        embedding_dimension=s.embedding_dimension,
        reranker_enabled=False,
    )

    print("Loading already-indexed titles from Qdrant...", flush=True)
    indexed = load_indexed_titles(retriever)
    print(f"  {len(indexed)} titles already indexed\n", flush=True)

    # ── Phase 1: collect unique Archive.org items ─────────────────────────────
    seen_ids: set[str] = set()
    items: list[dict] = []

    if not args.skip_download:
        for q in SEARCH_QUERIES:
            if len(items) >= args.limit * 2:
                break
            print(f"Search: {q[:70]}...", flush=True)
            results = search_archive(q, rows=200)
            new = 0
            for r in results:
                ident = r.get("identifier", "")
                if ident and ident not in seen_ids:
                    seen_ids.add(ident)
                    items.append(r)
                    new += 1
            print(f"  +{new} new items (total {len(items)})", flush=True)
            time.sleep(0.5)

        print(f"\nTotal unique items found: {len(items)}")
        # Save manifest for resuming
        manifest_path = out_dir / "archive_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        print(f"Manifest saved: {manifest_path}\n", flush=True)
    else:
        manifest_path = out_dir / "archive_manifest.json"
        if manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as f:
                items = json.load(f)
            print(f"Loaded {len(items)} items from manifest\n", flush=True)

    # ── Phase 2: download + ingest ────────────────────────────────────────────
    ok = skipped = failed = 0

    for item in items[:args.limit]:
        ident = item.get("identifier", "")
        raw_title = str(item.get("title", "") or ident)
        title = raw_title[:120]
        author = str(item.get("creator", "Unknown") or "Unknown")
        subjects = item.get("subject", [])
        if isinstance(subjects, str):
            subjects = [subjects]
        tags = ",".join(str(s) for s in (subjects or []))[:200]

        if title.lower().strip() in indexed:
            print(f"SKIP (indexed): {title[:70]}", flush=True)
            skipped += 1
            continue

        slug = slugify(title)
        local_pdf = staging / f"{slug}.pdf"
        local_txt = staging / f"{slug}.txt"

        # Check if already downloaded
        if not local_txt.exists():
            if not local_pdf.exists():
                result = get_best_pdf(ident)
                if result is None:
                    print(f"SKIP (no pdf): {title[:70]}", flush=True)
                    skipped += 1
                    continue
                url, fname = result
                print(f"DL: {title[:60]} [{ident}]", flush=True)
                if not download_file(url, local_pdf if fname.lower().endswith(".pdf") else local_txt):
                    failed += 1
                    continue

            # Extract text from PDF
            if local_pdf.exists():
                print(f"  Extract: {local_pdf.name}", flush=True)
                try:
                    text = extract_text_pdf(local_pdf, skip_ocr=args.no_ocr)
                except Exception as e:
                    print(f"  EXTRACT_ERR: {e}", flush=True)
                    failed += 1
                    local_pdf.unlink(missing_ok=True)
                    continue
                if len(text) < 500:
                    print(f"  SKIP (too little text: {len(text)} chars)", flush=True)
                    local_pdf.unlink(missing_ok=True)
                    skipped += 1
                    continue
                with open(local_txt, "w", encoding="utf-8", errors="replace") as f:
                    f.write(text)
                local_pdf.unlink(missing_ok=True)  # free disk space

        # Read text and ingest
        if local_txt.exists():
            text = local_txt.read_text(encoding="utf-8", errors="replace")
        else:
            skipped += 1
            continue

        if len(text) < 500:
            print(f"  SKIP (too little text: {len(text)} chars)", flush=True)
            skipped += 1
            continue

        chunks = chunk_text(text)
        meta = {"book": title, "author": author, "topic_tags": tags, "source": "archive.org", "identifier": ident}
        print(f"  Index: {title[:60]} → {len(chunks)} chunks", flush=True)
        try:
            ingest_chunks(chunks, meta, retriever)
            indexed.add(title.lower().strip())
            ok += 1
            print(f"  OK [{ok} total]", flush=True)
        except Exception as e:
            print(f"  INGEST_ERR: {e}", flush=True)
            failed += 1

    print(f"\n=== DONE: {ok} indexed, {skipped} skipped, {failed} failed ===")


if __name__ == "__main__":
    main()
