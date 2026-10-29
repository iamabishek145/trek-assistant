"""
rag.py — the agency's knowledge: data/agency.md

Two ways to give Claude the agency information:

1. FULL CONTEXT (used while the file is small, like now):
   send every section with every message. With ~10 sections (~2k tokens)
   this is faster and more reliable than searching: there's nothing to miss,
   and no embedding model has to run on the server's tiny free-tier CPU.

2. RAG (Retrieval-Augmented Generation), for agencies with lots of content:
   - Rule sections (inclusions, booking, discounts) are pinned: always sent.
   - The rest (treks, FAQs) goes into ChromaDB, which turns each chunk into
     an embedding (a list of numbers that captures its meaning).
   - search(question) finds the chunks whose meaning is closest.
   ChromaDB is only imported when RAG is actually used, because loading it
   and its model costs seconds and lots of memory on a small server.

Set RAG_MODE=always in .env to force RAG (e.g. to test it).
"""

import os
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "agency.md"
DB_PATH = Path(__file__).parent / "chroma_db"  # Chroma saves its data here

# Above this size, sending everything every time gets slow/expensive: use RAG
FULL_CONTEXT_MAX_CHARS = 15_000  # roughly 4,000 tokens

# Rules that can matter for ANY question (inclusions, discounts, payment).
# Search can miss these because they don't "sound like" the question,
# so in RAG mode they are always sent and kept out of the search index.
PINNED_HEADINGS = (
    "## About us",
    "## What's included",
    "## Not included",
    "## Booking and payment",
)


def split_into_chunks(text: str) -> list[str]:
    """Start a new chunk at every '## ' or '### ' heading."""
    chunks: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current:
                chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current).strip())

    # Drop tiny heading-only chunks (like "## Treks") and the file's title
    # block ("# ..."), which is a note for developers, not for travellers
    return [c for c in chunks if len(c) > 30 and not c.startswith("# ")]


def load_chunks() -> list[str]:
    return split_into_chunks(DATA_FILE.read_text(encoding="utf-8"))


def use_rag() -> bool:
    """RAG only when the agency info is too big to send in full."""
    if os.getenv("RAG_MODE") == "always":
        return True
    return sum(len(c) for c in load_chunks()) > FULL_CONTEXT_MAX_CHARS


def pinned_chunks() -> list[str]:
    """The always-included rule sections (RAG mode)."""
    return [c for c in load_chunks() if c.startswith(PINNED_HEADINGS)]


def trek_names() -> list[str]:
    """Trek names from the '## Treks' section, e.g. 'Poon Hill Trek'.
    Used so leads always store one of these exact names."""
    names, in_treks = [], False
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_treks = line.strip() == "## Treks"
        elif in_treks and line.startswith("### "):
            names.append(line[4:].strip())
    return names


_collection = None


def _get_collection():
    """Connect to ChromaDB the first time it's needed (heavy import)."""
    global _collection
    if _collection is None:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(DB_PATH),
            settings=Settings(anonymized_telemetry=False),  # no usage pings
        )
        # A "collection" is like a table: here, all chunks for one agency
        _collection = client.get_or_create_collection(name="agency")
    return _collection


def build_index() -> int:
    """(Re)load the searchable chunks (treks, FAQs) into Chroma."""
    collection = _get_collection()
    chunks = [c for c in load_chunks() if not c.startswith(PINNED_HEADINGS)]

    # Clear old chunks first, so edits to agency.md don't leave stale copies
    old_ids = collection.get()["ids"]
    if old_ids:
        collection.delete(ids=old_ids)

    ids = [f"chunk-{i}" for i in range(len(chunks))]
    collection.add(ids=ids, documents=chunks)  # Chroma embeds them here
    return len(chunks)


def search(question: str, k: int = 4) -> list[str]:
    """Return the k chunks whose meaning is closest to the question."""
    results = _get_collection().query(query_texts=[question], n_results=k)
    return results["documents"][0]
