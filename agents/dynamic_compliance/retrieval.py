"""
agents/dynamic_compliance/retrieval.py
Brightuity — RAG retrieval layer for the Dynamic Compliance agent.

Queries the persisted ChromaDB regulatory knowledge base and returns the
top-k semantically relevant legal provisions with full metadata, so the
Dynamic Compliance agent can ground its opinion in real cited law rather
than model memory.

The index is built by rag_corpus/build_index.py and must exist before this
module is used. Run build_index.py once after cloning the repo.

Public interface:
    retrieve_relevant_law(query, asset_type, jurisdiction, k) -> list[dict]
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# ── Configuration (must match rag_corpus/build_index.py) ─────────────────────

_EMBEDDING_MODEL  = "all-MiniLM-L6-v2"
_COLLECTION_NAME  = "brightuity_regulatory"
_INDEX_DIR        = str(Path(__file__).parent.parent.parent / "rag_corpus" / "chroma_index")


# ── Lazy-initialised singletons ────────────────────────────────────────────────
# ChromaDB client and embedding function are created once on first call and
# reused across all subsequent calls within the same process. This avoids
# reloading the ~22 MB sentence-transformer model on every retrieval.

_chroma_client = None
_embedding_fn  = None
_collection    = None


def _get_collection():
    """
    Return the ChromaDB collection, initialising on first call.
    Raises RuntimeError with a clear message if the index has not been built.
    """
    global _chroma_client, _embedding_fn, _collection

    if _collection is not None:
        return _collection

    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    index_path = Path(_INDEX_DIR)
    if not index_path.exists():
        raise RuntimeError(
            f"ChromaDB index not found at {_INDEX_DIR}.\n"
            "Run the build script first:  python rag_corpus/build_index.py"
        )

    _embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=_EMBEDDING_MODEL,
        device="cpu",
    )
    _chroma_client = chromadb.PersistentClient(path=_INDEX_DIR)
    _collection = _chroma_client.get_collection(
        name=_COLLECTION_NAME,
        embedding_function=_embedding_fn,
    )
    return _collection


# ── Public interface ───────────────────────────────────────────────────────────

def retrieve_relevant_law(
    query: str,
    asset_type: Optional[str] = None,
    jurisdiction: str = "EU",
    k: int = 5,
) -> list[dict]:
    """
    Retrieve the top-k most semantically relevant regulatory provisions for a
    given compliance query.

    The retrieval is purely semantic (dense vector search) — no keyword matching.
    The embedding model (all-MiniLM-L6-v2) maps both the query and the stored
    provisions to the same vector space; cosine similarity selects the closest.

    Args:
        query:       The free-text compliance question or case description.
                     E.g. "What authorisation does a German issuer need to tokenise
                     commercial property as an asset-referenced token under MiCA?"
        asset_type:  Optional asset type string (e.g. "Commercial Property",
                     "Luxury Villa") appended to the query to improve precision.
        jurisdiction: Currently "EU" (FCA and VARA can be added to the corpus later
                     and filtered here with a `where` clause).
        k:           Number of provisions to return (default 5).

    Returns:
        List of dicts, each representing one regulatory provision, ordered by
        descending relevance score (1 = perfect match, 0 = orthogonal):
        [
            {
                "id":           str,   # unique provision ID
                "regulation":   str,   # full regulation name + EU number
                "article":      str,   # article number and short title
                "jurisdiction": str,   # "EU", "UK", "UAE", etc.
                "topic":        str,   # short topic tag
                "text":         str,   # provision text (summary or verbatim)
                "score":        float, # relevance score 0–1 (higher = more relevant)
            }
        ]

    Raises:
        RuntimeError: if the ChromaDB index has not been built.
    """
    collection = _get_collection()

    # Enrich the query with asset type context for better retrieval precision
    full_query = query
    if asset_type:
        full_query = f"{asset_type} tokenisation: {query}"

    # Optional jurisdiction filter — passes through for now (all corpus is EU)
    where_filter = None
    if jurisdiction and jurisdiction != "EU":
        where_filter = {"jurisdiction": jurisdiction}

    results = collection.query(
        query_texts=[full_query],
        n_results=min(k, collection.count()),
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    passages: list[dict] = []
    ids       = results["ids"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for pid, meta, dist in zip(ids, metadatas, distances):
        # ChromaDB cosine distance: 0 = identical, 1 = orthogonal.
        # Convert to relevance score: 1 = perfect match.
        score = round(max(0.0, 1.0 - dist), 4)
        passages.append({
            "id":           pid,
            "regulation":   meta["regulation"],
            "article":      meta["article"],
            "jurisdiction": meta["jurisdiction"],
            "topic":        meta["topic"],
            "text":         meta["raw_text"],   # original text, not the indexed topic+text
            "score":        score,
        })

    return passages
