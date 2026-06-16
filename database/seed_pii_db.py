"""
database/seed_pii_db.py
Idempotent JSONB ingestion of all clients into the pii_clients PostgreSQL table.

Each client is stored as a single JSONB blob keyed by client_id, with request_id
as a separate indexed TEXT column so Zone 1 lookups stay fast.  Re-running this
script is always safe — all inserts are ON CONFLICT DO UPDATE upserts.

Usage:
    PII_DB_DSN=postgresql://user:pass@host/dbname python database/seed_pii_db.py

Environment:
    PII_DB_DSN  — PostgreSQL connection DSN (required when run as __main__).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_JSON_FILE = Path(__file__).parent / "brightuity_clients.json"

_DDL = """
CREATE TABLE IF NOT EXISTS pii_clients (
    client_id   TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL UNIQUE,
    client_data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pii_clients_request_id ON pii_clients (request_id);
"""

_UPSERT = """
INSERT INTO pii_clients (client_id, request_id, client_data)
VALUES (%s, %s, %s)
ON CONFLICT (client_id) DO UPDATE
    SET request_id  = EXCLUDED.request_id,
        client_data = EXCLUDED.client_data;
"""


def seed(dsn: str) -> int:
    """
    Upsert all clients from the JSON seed file into the pii_clients table.

    Creates the table and index if they do not exist.
    Returns the number of clients processed.
    """
    import psycopg
    from psycopg.types.json import Jsonb

    with open(_JSON_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    clients = data["clients"]

    with psycopg.connect(dsn) as conn:
        conn.execute(_DDL)
        for client in clients:
            conn.execute(_UPSERT, (
                client["client_id"],
                client["request_id"],
                Jsonb(client),
            ))
        conn.commit()

    return len(clients)


if __name__ == "__main__":
    dsn = os.getenv("PII_DB_DSN", "").strip()
    if not dsn:
        print("ERROR: PII_DB_DSN environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    n = seed(dsn)
    print(f"Seeded {n} clients into pii_clients.")
