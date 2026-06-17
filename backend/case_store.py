"""
backend/case_store.py
Brightuity — SQLite case record repository (Phase 1).

Repository pattern: ALL SQLite access lives here and only here.
main.py and tests never import sqlite3 directly.

Swapping SQLite → PostgreSQL (Phase 2) means:
  1. Replace _connect() with an asyncpg pool.
  2. Translate ? placeholders to $1 / $2 / … (asyncpg style).
  3. Replace TEXT JSON columns with JSONB.
  Everything above init_db() in main.py stays unchanged.

Schema design:
  Mirrors database/schema_db1.sql `cases` table (SQLite dialect).
  Key dialect translations:
    SERIAL            → INTEGER PRIMARY KEY AUTOINCREMENT
    JSONB             → TEXT  (JSON serialized as string)
    NOW()             → strftime('%Y-%m-%dT%H:%M:%SZ','now')
    REFERENCES clause → omitted (clients live in JSON, not in this DB)
  Three columns added beyond schema_db1.sql:
    pipeline_status   — orchestrator value; queryable without parsing JSON
    seal_status       — "sealed" | "blocked"; queryable without parsing JSON
    evidence_package  — full EvidencePackage JSON assembled by governance_audit
    decision_record_json — full orchestrator decision_record JSON

PII policy:
  full_name, passport_number, date_of_birth, address are NOT stored here.
  They remain in Zone 1 (brightuity_clients.json → DB1 PostgreSQL in Phase 2).
  This table holds only non-PII operational fields consistent with the
  field-whitelisting already enforced in main.py.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

def get_db_path() -> Path:
    """
    Return the SQLite database file path.

    Reads CASES_DB_PATH from environment at call time (not import time) so
    tests can override via os.environ without module reloading.
    Default: <project_root>/database/brightuity_cases.db
    """
    default = str(
        Path(__file__).parent.parent / "database" / "brightuity_cases.db"
    )
    return Path(os.getenv("CASES_DB_PATH", default))


# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_CASES = """
CREATE TABLE IF NOT EXISTS cases (
    id                   INTEGER  PRIMARY KEY AUTOINCREMENT,
    request_id           TEXT     NOT NULL UNIQUE,
    status               TEXT     NOT NULL DEFAULT 'pending',

    -- Initiation
    initiated_by         TEXT,
    initiated_at         TEXT,

    -- Agent verdicts: compact per-agent summary (not full LLM payloads)
    -- Schema: {"doc_auditor": {"verdict":…, "summary":…, "latency_ms":…, "model_used":…}, …}
    agent_verdicts       TEXT     NOT NULL DEFAULT '{}',

    -- Pipeline outcome (queryable without JSON parsing)
    pipeline_status      TEXT,
    gate_outcome         TEXT,

    -- Seal fields (queryable without JSON parsing)
    seal_status          TEXT,
    consensus_hash       TEXT,
    ecdsa_signature      TEXT,
    sealed_at            TEXT,
    band_chat_id         TEXT,

    -- Human decision (written when Head of Digital Assets signs — Phase 2)
    completed_at         TEXT,
    decision             TEXT,
    decision_reason      TEXT     NOT NULL DEFAULT '',
    decision_by          TEXT,
    esignature_hash      TEXT,

    -- Full JSON blobs (source of truth for detail views)
    evidence_package     TEXT,
    decision_record_json TEXT,

    created_at           TEXT     NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at           TEXT     NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
)
"""

_IDX_STATUS     = "CREATE INDEX IF NOT EXISTS idx_cases_status     ON cases(status)"
_IDX_REQUEST_ID = "CREATE INDEX IF NOT EXISTS idx_cases_request_id ON cases(request_id)"


# ── Connection helper ─────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """
    Open a new SQLite connection.

    WAL mode: allows concurrent readers while a writer holds the lock.
    check_same_thread=False: safe because we never share a connection across
    threads — each call to _connect() opens its own connection.
    """
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Public interface ──────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Idempotent schema initialiser. Safe to call on every startup.
    Creates the cases table and indexes only if they don't already exist.
    Also runs safe ALTER TABLE migrations for columns added after initial deploy.
    """
    with _connect() as conn:
        conn.execute(_CREATE_CASES)
        conn.execute(_IDX_STATUS)
        conn.execute(_IDX_REQUEST_ID)
        # Idempotent migration: add band_chat_id to existing databases.
        # SQLite raises OperationalError("duplicate column name: ...") if the
        # column already exists — catch and ignore that specific error only.
        try:
            conn.execute("ALTER TABLE cases ADD COLUMN band_chat_id TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    logger.info("case_store: initialised at %s", get_db_path())


def create_case_record(
    request_id: str,
    status: str = "pending",
    initiated_by: str | None = None,
) -> dict[str, Any]:
    """
    Insert a new case row and return it as a dict.

    Raises sqlite3.IntegrityError (UNIQUE constraint) if request_id exists.
    Callers should catch this and treat it as a 409 Conflict.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO cases (request_id, status, initiated_by, initiated_at,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (request_id, status, initiated_by, now, now, now),
        )
    result = get_case(request_id)
    assert result is not None
    return result


def get_case(request_id: str) -> dict[str, Any] | None:
    """Return the case row as a plain dict, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE request_id = ?", (request_id,)
        ).fetchone()
    return dict(row) if row else None


def list_cases(status: str | None = None) -> list[dict[str, Any]]:
    """
    Return all case rows, optionally filtered by status.
    Ordered by created_at ascending (chronological submission order).
    """
    with _connect() as conn:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM cases WHERE status = ? ORDER BY created_at ASC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cases ORDER BY created_at ASC"
            ).fetchall()
    return [dict(r) for r in rows]


def set_status(request_id: str, status: str) -> None:
    """Update the lifecycle status of an existing case."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE cases SET status = ?, updated_at = ? WHERE request_id = ?",
            (status, now, request_id),
        )
    logger.info("case_store: %s → %s", request_id, status)


def set_band_chat_id(request_id: str, chat_id: str) -> None:
    """Persist the Band chat room id for a case."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE cases SET band_chat_id = ?, updated_at = ? WHERE request_id = ?",
            (chat_id, now, request_id),
        )
    logger.info("case_store: band_chat_id set for %s (%s)", request_id, chat_id)


def save_pipeline_result(
    request_id: str,
    decision_record: dict[str, Any],
    evidence_package: dict[str, Any],
) -> None:
    """
    Persist the completed pipeline output for a case.

    Writes all queryable scalar fields (pipeline_status, gate_outcome, seal fields)
    plus the two full JSON blobs (evidence_package, decision_record_json).

    Does NOT update case.status — call set_status() separately so the transition
    is always validated by case_state.validate_transition().
    """
    seal   = decision_record.get("seal") or {}
    agents = decision_record.get("agents") or {}

    # Compact agent_verdicts: just the fields needed for audit queries.
    # Full LLM output stays in decision_record_json only.
    compact: dict[str, Any] = {}
    for name, result in agents.items():
        if result:
            compact[name] = {
                "verdict":    result.get("verdict"),
                "summary":    (result.get("summary") or "")[:300],
                "latency_ms": result.get("latency_ms"),
                "model_used": result.get("model_used"),
            }
    compact["consensus_signer"] = {
        "verdict":    seal.get("status"),
        "hash":       seal.get("canonical_hash"),
        "latency_ms": None,
    }

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE cases SET
                pipeline_status      = ?,
                gate_outcome         = ?,
                agent_verdicts       = ?,
                seal_status          = ?,
                consensus_hash       = ?,
                ecdsa_signature      = ?,
                sealed_at            = ?,
                evidence_package     = ?,
                decision_record_json = ?,
                updated_at           = ?
            WHERE request_id = ?
            """,
            (
                decision_record.get("pipeline_status"),
                decision_record.get("gate_outcome"),
                json.dumps(compact, ensure_ascii=False),
                seal.get("status"),
                seal.get("canonical_hash"),
                seal.get("signature"),
                seal.get("sealed_at"),
                json.dumps(evidence_package, ensure_ascii=False),
                json.dumps(decision_record, ensure_ascii=False),
                now,
                request_id,
            ),
        )
    logger.info(
        "case_store: saved result for %s (pipeline_status=%s seal=%s)",
        request_id,
        decision_record.get("pipeline_status"),
        seal.get("status"),
    )


def get_evidence_package(request_id: str) -> dict[str, Any] | None:
    """
    Return the stored EvidencePackage for a completed case.
    Returns None if the case doesn't exist or the pipeline hasn't run yet.
    """
    case = get_case(request_id)
    if not case or case.get("evidence_package") is None:
        return None
    return json.loads(case["evidence_package"])


def save_human_authorization(
    request_id: str,
    decision: str,
    decision_reason: str,
    decision_by: str,
    esignature_hash: str,
    human_authorization: dict[str, Any],
) -> None:
    """
    Persist the signed human decision and patch the stored evidence package.

    Writes scalar columns (completed_at, decision, decision_reason, decision_by,
    esignature_hash) AND patches the evidence_package JSON blob in one atomic
    transaction so the DB never holds a partially-updated package.

    The evidence_package is patched in two places:
      • human_authorization ← the completed signed block
      • case_summary.final_decision ← decision ("approved" | "rejected")

    Does NOT update case.status — call set_status() separately so the
    transition is always validated by case_state.validate_transition().

    # Phase 3: INSERT a row into audit_log with event_type="human.decision"
    # and event_detail = {"decision": decision, "esignature_hash": esignature_hash}.
    # The audit_log table is defined in database/schema_db1.sql.
    """
    # Load the current evidence_package, patch it, and re-serialize
    case = get_case(request_id)
    if case is None or case.get("evidence_package") is None:
        raise ValueError(f"No evidence package found for '{request_id}' — run the pipeline first.")

    pkg: dict[str, Any] = json.loads(case["evidence_package"])
    pkg["human_authorization"]           = human_authorization
    pkg["case_summary"]["final_decision"] = decision

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            """
            UPDATE cases SET
                completed_at    = ?,
                decision        = ?,
                decision_reason = ?,
                decision_by     = ?,
                esignature_hash = ?,
                evidence_package = ?,
                updated_at      = ?
            WHERE request_id = ?
            """,
            (
                now, decision, decision_reason, decision_by, esignature_hash,
                json.dumps(pkg, ensure_ascii=False),
                now, request_id,
            ),
        )
    logger.info(
        "case_store: human authorization saved for %s (decision=%s)",
        request_id, decision,
    )
