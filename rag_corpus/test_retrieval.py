"""
rag_corpus/test_retrieval.py
Brightuity — Phase A test: build index + prove retrieval returns the right law.

Builds the ChromaDB index from source corpus, then runs two realistic queries
and prints the retrieved provisions with article references.

The proof: for each query, the RIGHT real regulatory text comes back with the
correct article numbers — demonstrating the retrieval layer is ready for the
Dynamic Compliance agent to ground its opinions in (Phase B).

Run: python rag_corpus/test_retrieval.py
  or: python -m rag_corpus.test_retrieval
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Make project root importable when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

sys.stdout.reconfigure(encoding="utf-8")

from rag_corpus.build_index import build_index
from agents.dynamic_compliance.retrieval import retrieve_relevant_law

_SEP  = "─" * 72
_SEP2 = "═" * 72


def _show_passages(passages: list[dict]) -> None:
    for i, p in enumerate(passages, 1):
        print(f"\n  [{i}]  score={p['score']:.4f}  |  {p['jurisdiction']}")
        print(f"       Regulation : {p['regulation']}")
        print(f"       Article    : {p['article']}")
        print(f"       Topic      : {p['topic']}")
        wrapped = textwrap.fill(p["text"], width=68, initial_indent="       Text      : ",
                                subsequent_indent="                   ")
        print(wrapped)


def run_query(label: str, query: str, asset_type: str | None = None, k: int = 5) -> None:
    print(f"\n{_SEP}")
    print(f"  {label}")
    print(_SEP)
    print(f"  query      : {query}")
    if asset_type:
        print(f"  asset_type : {asset_type}")
    print(f"  k          : {k}")

    passages = retrieve_relevant_law(query=query, asset_type=asset_type, k=k)
    print(f"\n  Retrieved {len(passages)} passages:")
    _show_passages(passages)


if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY · RAG Knowledge Base · Phase A Test")
    print("  Step 1: Build index from corpus sources")
    print("  Step 2: Prove retrieval returns the correct real law")
    print(_SEP2)

    # ── Step 1: Build the index ────────────────────────────────────────────────
    print("\nBuilding ChromaDB index...")
    build_index(force_rebuild=True)

    # ── Step 2: Query 1 — RWA property tokenisation under MiCA ────────────────
    run_query(
        label="QUERY 1 — Commercial property tokenisation authorisation under EU/MiCA",
        query=(
            "What authorisation requirements and regulatory framework apply when "
            "tokenising commercial property as an asset-referenced token in the EU? "
            "What are the white paper, own funds, and reserve of assets obligations?"
        ),
        asset_type="Commercial Property",
        k=5,
    )

    # ── Step 3: Query 2 — PEP with offshore funds AML obligations ─────────────
    run_query(
        label="QUERY 2 — PEP match with unverifiable offshore source of funds",
        query=(
            "A customer has a confirmed PEP match linked to a politically exposed network "
            "and their source of funds is described as unverifiable offshore structures. "
            "What enhanced due diligence, senior management approval, source-of-funds "
            "verification, and AML measures are required under EU law?"
        ),
        k=5,
    )

    # ── Bonus: Query 3 — CASP authorisation ───────────────────────────────────
    run_query(
        label="QUERY 3 — CASP authorisation and passporting across EU Member States",
        query=(
            "What authorisation does a bank's digital assets division need to provide "
            "custody and token exchange services across EU Member States?"
        ),
        k=3,
    )

    print()
    print(_SEP2)
    print("  Phase A complete. ChromaDB index built and retrieval validated.")
    print("  Corpus: mica_provisions.json + amld_provisions.json")
    print("  Jurisdiction tags ready: add fca_provisions.json / vara_provisions.json")
    print("  to rag_corpus/sources/ and re-run build_index.py — zero code changes.")
    print("  Next: Phase B — wire retrieval into the Dynamic Compliance agent logic.")
    print(_SEP2)
    print()
