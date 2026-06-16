"""
backend/pii_store.py
Swappable PII data layer for the backend API.

Environment switch (PII_DB_DSN — read at call time):
    set   → read from PostgreSQL (Zone 1 / db1_pii container)
    unset → read from the local JSON seed file (Phase 1 / dev / CI)

Public surface: one function.
    load_clients() -> dict[str, dict[str, Any]]
        Keyed by request_id. Shape is identical to the JSON path —
        callers see no difference between the two paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_JSON_FILE = Path(__file__).parent.parent / "database" / "brightuity_clients.json"


def load_clients() -> dict[str, dict[str, Any]]:
    """
    Return all client records keyed by request_id.

    Reads PII_DB_DSN at call time so the switch can be toggled in tests
    without reimporting this module.
    """
    dsn = os.getenv("PII_DB_DSN", "").strip()
    if dsn:
        return _load_from_postgres(dsn)
    return _load_from_json()


def _load_from_json() -> dict[str, dict[str, Any]]:
    with open(_JSON_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {c["request_id"]: c for c in raw["clients"]}


def _load_from_postgres(dsn: str) -> dict[str, dict[str, Any]]:
    import psycopg  # optional dep — only present when PII_DB_DSN is set

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT request_id, client_data FROM pii_clients ORDER BY client_id"
        ).fetchall()
    return {row[0]: row[1] for row in rows}
