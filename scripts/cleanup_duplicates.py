"""
Delete duplicate/stale Qdrant entries, keeping the better version.
"""
from __future__ import annotations
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.config import get_settings
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

# Titles to DELETE (the worse/older version)
TO_DELETE = [
    "Jaimini-Sutras",               # replaced by "Jaimini Sutras" (808 chunks)
    "Uttara Kalamritam",            # replaced by "Uttara Kalamrita" (502 chunks)
    "2015.83552.Three-Hundred-Important-Combinations_text",  # replaced by "Three Hundred Important Combinations"
    "Muhurta Martanda",             # only 12 chunks — tiny stub; "Muhurta Martanda Sri Moduram" (284) is better
    "28Nakshatras-TheRealSecretsofVedicAstrologyAne-book (1)",  # exact duplicate
]


def delete_by_title(client: QdrantClient, collection: str, title: str) -> None:
    client.delete(
        collection_name=collection,
        points_selector=Filter(
            must=[FieldCondition(key="book", match=MatchValue(value=title))]
        ),
        wait=True,
    )
    print(f"  DELETED: {title}")


def main() -> None:
    settings = get_settings()
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=60,
    )

    print(f"Cleaning up {len(TO_DELETE)} duplicate entries...\n")
    for title in TO_DELETE:
        try:
            delete_by_title(qdrant, settings.books_collection, title)
        except Exception as e:
            print(f"  ERROR deleting '{title}': {e}")

    print("\nDone. Verify:")
    import requests
    resp = requests.get(
        "https://astrobrobackend-production.up.railway.app/api/books/list",
        timeout=20,
    )
    data = resp.json()
    print(f"  Total chunks: {data['total_chunks']} | Books: {len(data['books'])}")


if __name__ == "__main__":
    main()
