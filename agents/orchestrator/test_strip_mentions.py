"""
agents/orchestrator/test_strip_mentions.py
Unit tests for _strip_mentions() in band_agents/orchestrator_adapter.py.

Run via: pytest agents/orchestrator/test_strip_mentions.py -v
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from band_agents.orchestrator_adapter import _strip_mentions


def test_uuid_bracket_mention_at_start_stripped():
    raw = "@[[18cb4fe5-7d9d-4821-b4d3-c948eda44c37]] 🚨 KYC Guardian — REQ-2043 — HALT: sanctions match"
    assert _strip_mentions(raw) == "🚨 KYC Guardian — REQ-2043 — HALT: sanctions match"


def test_multiple_uuid_bracket_mentions_stripped():
    raw = "@[[aaaa-bbbb]] @[[cccc-dddd]] **PASS** — all docs verified"
    assert _strip_mentions(raw) == "**PASS** — all docs verified"


def test_no_mentions_unchanged():
    plain = "**FAIL** — missing notarisation on page 3"
    assert _strip_mentions(plain) == plain


def test_in_sentence_at_sign_preserved():
    # '@' inside prose must NOT be stripped — only leading mention tokens.
    text = "Contact compliance at legal@brightuity.com for clarification."
    assert _strip_mentions(text) == text


def test_leading_bare_handle_stripped():
    # Band sometimes produces @Handle (no UUID brackets) at the very start.
    raw = "@Orchestrator **PASS** — stress test cleared"
    assert _strip_mentions(raw) == "**PASS** — stress test cleared"


def test_uuid_token_then_bare_handle_both_stripped():
    raw = "@[[18cb4fe5-7d9d-4821-b4d3-c948eda44c37]] @Orchestrator **HALT** — watchlist hit"
    assert _strip_mentions(raw) == "**HALT** — watchlist hit"


def test_mid_sentence_at_sign_not_stripped():
    # '^' anchor on _LEADING_HANDLE_RE means only position-0 handles are removed.
    text = "Issued by the authority of @regulator per MiCA Article 17."
    assert "@regulator" in _strip_mentions(text)


def test_empty_string_returns_empty():
    assert _strip_mentions("") == ""


def test_only_uuid_token_returns_empty():
    assert _strip_mentions("@[[18cb4fe5-7d9d-4821-b4d3-c948eda44c37]]") == ""


def test_verdict_line_representative():
    # Typical KYC HALT reply as it arrives from Band.
    raw = (
        "@[[18cb4fe5-7d9d-4821-b4d3-c948eda44c37]] "
        "**HALT** — REQ-2043\n\n"
        "KYC screening identified a sanctions-list match for the beneficial owner. "
        "Tokenization is blocked."
    )
    result = _strip_mentions(raw)
    assert result.startswith("**HALT**")
    assert "@[[" not in result
    assert "sanctions-list match" in result


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
