"""
backend/test_pii_store_parity.py
Parity test: JSON path vs PostgreSQL path for pii_store.load_clients().

Requirements:
    BRIGHTUITY_TEST_PG_DSN — PostgreSQL DSN for a test database.
    If not set this entire module is skipped with a clear message.

What it verifies:
    1. Seeds the test database with all 100 clients via seed_pii_db.seed().
    2. Calls pii_store.load_clients() with PII_DB_DSN="" (JSON path).
    3. Calls pii_store.load_clients() with PII_DB_DSN=test DSN (PG path).
    4. Asserts the returned dicts are deep-equal on every key/value pair.

Run:
    BRIGHTUITY_TEST_PG_DSN=postgresql://user:pass@localhost/testdb \\
        pytest backend/test_pii_store_parity.py -v
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

_DSN = os.getenv("BRIGHTUITY_TEST_PG_DSN", "").strip()
if not _DSN:
    pytest.skip(
        "BRIGHTUITY_TEST_PG_DSN not set — skipping PII store parity test. "
        "Set to a PostgreSQL DSN pointing at a test database to run this suite.",
        allow_module_level=True,
    )

from database.seed_pii_db import seed  # noqa: E402 — only reached when DSN is set
from backend.pii_store import load_clients  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def seed_test_db():
    n = seed(_DSN)
    assert n == 100, f"Expected 100 clients seeded, got {n}"


def test_load_clients_parity():
    """JSON and Postgres paths must return deep-equal dicts for all 100 clients."""
    # JSON path — ensure PII_DB_DSN is not set.
    with patch.dict(os.environ, {"PII_DB_DSN": ""}):
        json_result = load_clients()

    # Postgres path.
    with patch.dict(os.environ, {"PII_DB_DSN": _DSN}):
        pg_result = load_clients()

    assert len(json_result) == 100, f"JSON path returned {len(json_result)} clients"
    assert len(pg_result) == 100, f"PG path returned {len(pg_result)} clients"

    assert set(json_result.keys()) == set(pg_result.keys()), (
        "request_id key sets differ between JSON and PG paths"
    )

    mismatches: list[str] = []
    for request_id, json_client in json_result.items():
        pg_client = pg_result[request_id]
        if json_client != pg_client:
            diff_keys = [
                k for k in set(json_client) | set(pg_client)
                if json_client.get(k) != pg_client.get(k)
            ]
            mismatches.append(
                f"{request_id}: fields differ: {diff_keys}"
            )

    assert not mismatches, (
        f"{len(mismatches)} client(s) differ between JSON and PG paths:\n"
        + "\n".join(mismatches)
    )


def test_json_fallback_when_dsn_unset():
    """load_clients() returns JSON data when PII_DB_DSN is empty."""
    with patch.dict(os.environ, {"PII_DB_DSN": ""}):
        result = load_clients()
    assert len(result) == 100
    # Spot-check the three anchor clients.
    assert "REQ-2041" in result
    assert "REQ-2042" in result
    assert "REQ-2043" in result
    # expected_outcome is present in Zone 1 data (not stripped by pii_store).
    assert result["REQ-2041"]["expected_outcome"] == "approve"
