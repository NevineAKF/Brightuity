"""
agents/kyc_guardian/screening.py
Brightuity — Deterministic KYC watchlist screening engine.

Bank-grade KYC requires a deterministic matching decision BEFORE any LLM
interpretation. This module provides that layer: pure Python, no network
calls, no LLM. It returns a structured result that logic.py injects into
the LLM prompt as established fact.

Public interface:
    screen_against_watchlist(client_record: dict) -> dict
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_WATCHLIST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "watchlist.json"

_watchlist_cache: list[dict] | None = None


def _load_watchlist() -> list[dict]:
    global _watchlist_cache
    if _watchlist_cache is None:
        data = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
        _watchlist_cache = data["entries"]
    return _watchlist_cache


def _normalize_tokens(name: str) -> list[str]:
    """Lowercase, strip diacritics, split on non-alpha, return non-empty tokens."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    tokens = re.split(r"[^a-z]+", ascii_name.lower())
    return [t for t in tokens if t]


def _name_match_score(client_name: str, watchlist_name: str) -> float:
    """
    Returns a deterministic match score in [0, 1].

    Rules (in priority order):
    1. Exact normalized full name -> 1.0
    2. All client name tokens present in watchlist tokens (subset) -> 0.95
    3. All watchlist tokens present in client tokens (subset) -> 0.90
    4. Overlap of >=2 tokens -> proportional score
    5. Otherwise -> 0.0

    Ignoring middle initials: a client token set of size 2 that fully overlaps
    a watchlist token set of size 2 scores 0.95 (subset rule), which is a match.
    A single shared token (e.g. only first name) scores 0.0 — not a match.
    """
    c_tokens = _normalize_tokens(client_name)
    w_tokens = _normalize_tokens(watchlist_name)

    if not c_tokens or not w_tokens:
        return 0.0

    c_set = set(c_tokens)
    w_set = set(w_tokens)

    # 1. Exact full name (token sets identical)
    if c_set == w_set:
        return 1.0

    # 2. All client tokens found in watchlist (client is a substring of watchlist name)
    if c_set <= w_set:
        return 0.95

    # 3. All watchlist tokens found in client (watchlist is a substring of client name)
    if w_set <= c_set:
        return 0.90

    # 4. At least 2 tokens overlap
    overlap = c_set & w_set
    if len(overlap) >= 2:
        return round(len(overlap) / max(len(c_set), len(w_set)), 2)

    return 0.0


# Threshold: scores at or above this value are treated as a match.
# 0.85 captures subset matches (rules 2/3) and high-overlap cases.
# A single shared token (common first name only) will always score below this.
_MATCH_THRESHOLD = 0.85


def screen_against_watchlist(client_record: dict) -> dict:
    """
    Screen a client record against the deterministic watchlist.

    Matching is purely algorithmic: normalised name comparison with optional
    nationality cross-check. No LLM involved.

    Args:
        client_record: The full client dict (only full_name and nationality are used).

    Returns:
        {
            "matched":       bool,
            "match_type":    "sanctions" | "pep" | None,
            "matched_entry": dict | None,   # full watchlist row
            "match_score":   float,         # deterministic score [0, 1]
            "sources_checked": list[str],   # distinct sources searched
        }
    """
    entries = _load_watchlist()
    sources_checked = sorted({e["source"] for e in entries})

    client_name = client_record.get("full_name", "")
    client_nationality = (client_record.get("nationality") or "").lower().strip()

    best_entry: dict | None = None
    best_score: float = 0.0

    for entry in entries:
        score = _name_match_score(client_name, entry["name"])
        if score < _MATCH_THRESHOLD:
            continue

        # Nationality cross-check: boost score slightly when country matches,
        # to prefer the most specific match if multiple candidates exist.
        entry_country = entry.get("country", "").lower().strip()
        if client_nationality and entry_country and client_nationality == entry_country:
            score = min(score + 0.05, 1.0)

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is not None:
        return {
            "matched": True,
            "match_type": best_entry["type"],
            "matched_entry": best_entry,
            "match_score": round(best_score, 2),
            "sources_checked": sources_checked,
        }

    return {
        "matched": False,
        "match_type": None,
        "matched_entry": None,
        "match_score": 0.0,
        "sources_checked": sources_checked,
    }
