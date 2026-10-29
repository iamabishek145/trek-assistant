"""
rag.py — Day 3: Retrieval-Augmented Generation (RAG)

1. Split data/agency.md into small chunks (one per section).
   Rule sections (inclusions, booking, discounts) are pinned: always sent.
2. Store the rest (treks, FAQs) in ChromaDB. Chroma turns each chunk into an embedding
   (a list of numbers that captures its meaning) using a small local model.
3. search(question) finds the chunks whose meaning is closest to the question.
"""

from pathlib import Path

import chromadb

DATA_FILE = Path(__file__).parent / "data" / "agency.md"
DB_PATH = Path(__file__).parent / "chroma_db"  # Chroma saves its data here

# Connect to (or create) a local Chroma database stored on disk
chroma = chromadb.PersistentClient(path=str(DB_PATH))

# A "collection" is like a table: here, all chunks for one agency
collection = chroma.get_or_create_collection(name="agency")

# Rules that can matter for ANY question (inclusions, discounts, payment).
# Search can miss these because they don't "sound like" the question,
# so they are always sent to Claude and kept out of the search index.
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

    # Drop tiny chunks that are only a heading, like "## Treks"
    return [chunk for chunk in chunks if len(chunk) > 30]


def load_chunks() -> list[str]:
    return split_into_chunks(DATA_FILE.read_text(encoding="utf-8"))


def pinned_chunks() -> list[str]:
    """The always-included rule sections."""
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


def build_index() -> int:
    """(Re)load the searchable chunks (treks, FAQs) into Chroma."""
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
    results = collection.query(query_texts=[question], n_results=k)
    return results["documents"][0]
