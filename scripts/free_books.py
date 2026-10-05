"""Download, chunk and upload the public-domain specialist books (catalogue: app/rag/free_books.py).

    python scripts/free_books.py plan [--samples N]        what would be uploaded; no network, nothing uploaded
    python scripts/free_books.py fetch                     download missing OCR texts into books_free/
    python scripts/free_books.py ingest [--only ID ...]    embed and upload into the specialist collection
    python scripts/free_books.py verify                    counts per domain and sample searches
    python scripts/free_books.py rollback --yes            delete everything this batch uploaded

The books go into their own collection (settings.specialist_collection), never the main Vedic one, so the
chat only reads them for tarot, numerology, Vastu, festival, calendar and remedy questions (app/rag/scope.py).
Uploads are idempotent: re-running replaces the same points.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.rag.free_books import BATCH_ID, BY_ID, MANIFEST, chunk_book  # noqa: E402

BOOKS_DIR = ROOT / "books_free"
UA = {"User-Agent": "AstroBro-free-books/1.0 (public-domain texts for a Vedic astrology app)"}

SAMPLE_QUERIES = {
    "tarot": "What does the Tower card mean when it appears reversed?",
    "numerology": "What is the meaning of the number 7?",
    "vastu": "Which direction is best for the kitchen and the main door of a house?",
    "festivals": "How is Holi celebrated and what is its origin?",
    "calendar": "How is a lunar month named and when does the Hindu year begin?",
    "lore": "How are gems such as ruby and pearl described and what are they used for?",
}


def _client(grpc: bool = False):
    from qdrant_client import QdrantClient

    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=120, prefer_grpc=grpc), s


def _selected(only: list[str] | None):
    if not only:
        return list(MANIFEST)
    unknown = [i for i in only if i not in BY_ID]
    if unknown:
        raise SystemExit(f"Unknown book id(s): {', '.join(unknown)}. Known: {', '.join(BY_ID)}")
    return [BY_ID[i] for i in only]


def _read(spec) -> str:
    path = BOOKS_DIR / spec.local_file
    if not path.exists():
        raise SystemExit(f"Missing {path.name}. Run: python scripts/free_books.py fetch")
    return path.read_text(encoding="utf-8", errors="replace")


# ── fetch ─────────────────────────────────────────────────────────────────────

def cmd_fetch(args) -> None:
    BOOKS_DIR.mkdir(exist_ok=True)
    for spec in _selected(args.only):
        path = BOOKS_DIR / spec.local_file
        if path.exists() and path.stat().st_size > 10_000:
            print(f"have   {spec.id} ({path.stat().st_size // 1024} KB)")
            continue
        url = f"https://archive.org/download/{spec.archive_id}/{urllib.parse.quote(spec.archive_file)}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as resp:
                    data = resp.read()
                if len(data) < 10_000 or data.lstrip()[:5].lower() == b"<html":
                    raise RuntimeError(f"unexpected response ({len(data)} bytes) - the item may be access-restricted")
                path.write_bytes(data)
                print(f"fetched {spec.id} ({len(data) // 1024} KB) from {spec.source_url}")
                break
            except Exception as exc:
                if attempt == 2:
                    print(f"FAILED {spec.id}: {exc}")
                else:
                    time.sleep(2 ** attempt)


# ── plan ──────────────────────────────────────────────────────────────────────

def _chunks_for(specs):
    seen: dict[str, set[str]] = {}
    for spec in specs:
        yield spec, *chunk_book(spec, _read(spec), seen=seen.setdefault(spec.title, set()))


def cmd_plan(args) -> None:
    total = 0
    by_domain: dict[str, int] = {}
    for spec, chunks, st in _chunks_for(_selected(args.only)):
        total += len(chunks)
        by_domain[spec.domain] = by_domain.get(spec.domain, 0) + len(chunks)
        print(f"{spec.id:40s} {spec.domain:10s} kept {st['kept']:5d} of {st['candidates']:5d}  "
              f"(unreadable {st['unreadable']}, off-topic {st['off_topic']}, duplicate {st['duplicate']})")
        for c in chunks[: args.samples]:
            print("     |", c.text[:230].replace("\n", " "))
    print(f"\nTOTAL {total} chunks  by domain: {by_domain}")


# ── ingest ────────────────────────────────────────────────────────────────────

def _ensure_collection(client, name: str, dim: int) -> None:
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    if not client.collection_exists(name):
        client.create_collection(name, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
        print(f"created collection {name}")
    for field in ("domain", "batch_id", "book"):
        client.create_payload_index(name, field_name=field, field_schema=PayloadSchemaType.KEYWORD)


def _upload(fast, rest, collection: str, points) -> None:
    """Upsert one batch; the first try uses gRPC (about twice as fast), retries fall back to plain REST."""
    for attempt in range(3):
        try:
            (fast if attempt == 0 else rest).upsert(collection, points=points, wait=True)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def cmd_ingest(args) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from fastembed import TextEmbedding
    from qdrant_client.models import PointStruct

    rest, s = _client()
    fast, _ = _client(grpc=True)
    if not s.specialist_collection:
        raise SystemExit("settings.specialist_collection is empty")
    model = s.embedding_model if "/" in s.embedding_model else f"sentence-transformers/{s.embedding_model}"
    embedder = TextEmbedding(model)
    _ensure_collection(rest, s.specialist_collection, s.embedding_dimension)

    with ThreadPoolExecutor(max_workers=3) as pool:       # uploads overlap with embedding the next batch
        for spec, chunks, st in _chunks_for(_selected(args.only)):
            print(f"{spec.id}: uploading {len(chunks)} chunks (dropped {st['unreadable']} unreadable, "
                  f"{st['off_topic']} off-topic, {st['duplicate']} duplicate)", flush=True)
            futures = []
            for i in range(0, len(chunks), 64):
                batch = chunks[i:i + 64]
                vectors = [v.tolist() for v in embedder.embed([c.text for c in batch])]
                points = [
                    PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_OID, c.chunk_id)), vector=vec,
                                payload={**c.metadata, "text": c.text, "chunk_id": c.chunk_id})
                    for c, vec in zip(batch, vectors)
                ]
                futures.append(pool.submit(_upload, fast, rest, s.specialist_collection, points))
                if len(futures) >= 6:                      # bound memory and surface errors early
                    futures.pop(0).result()
            for f in futures:
                f.result()
    print("done")
    cmd_verify(args)


# ── verify / rollback ─────────────────────────────────────────────────────────

def _batch_filter():
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must=[FieldCondition(key="batch_id", match=MatchValue(value=BATCH_ID))])


def cmd_verify(args) -> None:
    from fastembed import TextEmbedding
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client, s = _client()
    name = s.specialist_collection
    if not client.collection_exists(name):
        raise SystemExit(f"collection {name} does not exist yet")
    info = client.get_collection(name)
    print(f"collection {name}: {info.points_count} points, status {info.status}")
    print(f"batch {BATCH_ID}: {client.count(name, count_filter=_batch_filter(), exact=True).count} points")
    for domain in ("tarot", "numerology", "vastu", "festivals", "calendar", "lore"):
        n = client.count(name, count_filter=Filter(must=[FieldCondition(key="domain", match=MatchValue(value=domain))]),
                         exact=True).count
        print(f"  {domain:11s} {n}")

    model = s.embedding_model if "/" in s.embedding_model else f"sentence-transformers/{s.embedding_model}"
    embedder = TextEmbedding(model)
    for domain, query in SAMPLE_QUERIES.items():
        vec = next(iter(embedder.embed([query]))).tolist()
        hits = client.query_points(
            name, query=vec, limit=2,
            query_filter=Filter(must=[FieldCondition(key="domain", match=MatchValue(value=domain))]),
        ).points
        print(f"\n[{domain}] {query}")
        for h in hits:
            print(f"   {h.score:.3f} {h.payload['book']}: {h.payload['text'][:170]!r}")


def cmd_rollback(args) -> None:
    from qdrant_client.models import FilterSelector

    if not args.yes:
        raise SystemExit("Refusing to delete without --yes")
    client, s = _client()
    before = client.count(s.specialist_collection, count_filter=_batch_filter(), exact=True).count
    client.delete(s.specialist_collection, points_selector=FilterSelector(filter=_batch_filter()), wait=True)
    print(f"deleted {before} points of batch {BATCH_ID} from {s.specialist_collection}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("fetch", cmd_fetch), ("ingest", cmd_ingest), ("verify", cmd_verify),
                     ("rollback", cmd_rollback)):
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
        if name in ("plan", "fetch", "ingest"):
            sp.add_argument("--only", nargs="+", metavar="ID")
        if name == "plan":
            sp.add_argument("--samples", type=int, default=0)
        if name == "rollback":
            sp.add_argument("--yes", action="store_true")
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
