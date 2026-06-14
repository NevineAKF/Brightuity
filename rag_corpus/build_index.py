"""
rag_corpus/build_index.py
Brightuity — Build the ChromaDB regulatory knowledge base.

Loads the source corpus (mica_provisions.json + amld_provisions.json),
generates embeddings using sentence-transformers/all-MiniLM-L6-v2 (offline,
CPU-only, no API key), and persists a ChromaDB collection to disk.

Run once before using the Dynamic Compliance agent:
    python rag_corpus/build_index.py

The resulting index is stored at rag_corpus/chroma_index/ and is read by
agents/dynamic_compliance/retrieval.py without rebuilding every call.

Adding new jurisdictions (FCA, VARA):
    1. Create rag_corpus/sources/fca_provisions.json (same schema)
    2. Re-run this script — it rebuilds from all files in sources/
    No other code changes needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

_CORPUS_DIR  = Path(__file__).parent / "sources"
_INDEX_DIR   = Path(__file__).parent / "chroma_index"

# These must match the constants in agents/dynamic_compliance/retrieval.py
_COLLECTION_NAME  = "brightuity_regulatory"
_EMBEDDING_MODEL  = "all-MiniLM-L6-v2"


# ── Load corpus ────────────────────────────────────────────────────────────────

def _load_corpus() -> list[dict]:
    """Load all JSON provision files from the sources directory."""
    provisions: list[dict] = []
    source_files = sorted(_CORPUS_DIR.glob("*.json"))
    if not source_files:
        raise FileNotFoundError(f"No source files found in {_CORPUS_DIR}")

    for path in source_files:
        batch = json.loads(path.read_text(encoding="utf-8"))
        print(f"  Loaded {len(batch):>3} provisions from {path.name}")
        provisions.extend(batch)

    print(f"  Total: {len(provisions)} provisions across {len(source_files)} source files")
    return provisions


# ── Build index ────────────────────────────────────────────────────────────────

def build_index(force_rebuild: bool = True) -> None:
    """
    Build (or rebuild) the ChromaDB collection from the corpus sources.

    Args:
        force_rebuild: If True (default), deletes the existing collection before
                       rebuilding. Set to False to skip if collection already exists.
    """
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    print()
    print("═" * 64)
    print("  BRIGHTUITY · RAG Index Builder")
    print("  Embedding model : all-MiniLM-L6-v2  (offline, CPU)")
    print("  Vector store    : ChromaDB persistent  (local, in-process)")
    print(f"  Index path      : {_INDEX_DIR}")
    print("═" * 64)
    print()

    # Load source corpus
    print("[ 1/4 ] Loading corpus sources...")
    provisions = _load_corpus()
    print()

    # Set up embedding function
    print("[ 2/4 ] Initialising embedding model (downloads ~22 MB on first run)...")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=_EMBEDDING_MODEL,
        device="cpu",
    )
    print(f"  Model: {_EMBEDDING_MODEL}  ✓")
    print()

    # Connect to ChromaDB persistent store
    print("[ 3/4 ] Connecting to ChromaDB persistent store...")
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_INDEX_DIR))

    if force_rebuild:
        try:
            client.delete_collection(_COLLECTION_NAME)
            print(f"  Deleted existing collection '{_COLLECTION_NAME}' (rebuilding)")
        except Exception:
            pass  # Collection did not exist yet

    collection = client.create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for semantic search
    )
    print(f"  Created collection '{_COLLECTION_NAME}'")
    print()

    # Add documents
    print(f"[ 4/4 ] Embedding and indexing {len(provisions)} provisions...")
    ids:       list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for p in provisions:
        ids.append(p["id"])
        # Embed the text combined with topic tag — improves retrieval precision
        documents.append(f"{p['topic']}\n\n{p['text']}")
        metadatas.append({
            "regulation":  p["regulation"],
            "article":     p["article"],
            "jurisdiction": p["jurisdiction"],
            "topic":       p["topic"],
            "verbatim":    str(p.get("verbatim", False)),
            "source_note": p.get("source_note", ""),
            # Store original text separately so we can return it without the topic prefix
            "raw_text":    p["text"],
        })

    # ChromaDB batches internally but accepts all at once for small corpora
    collection.add(ids=ids, documents=documents, metadatas=metadatas)

    count = collection.count()
    print(f"  Indexed {count} provisions  ✓")
    print()
    print("  Done. Index ready at:  rag_corpus/chroma_index/")
    print("  Retrieval:             agents/dynamic_compliance/retrieval.py")
    print("═" * 64)
    print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build_index(force_rebuild=True)
