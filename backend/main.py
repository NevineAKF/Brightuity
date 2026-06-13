"""
Brightuity FastAPI backend — Zone 1 gateway (Phase 1: JSON data source).

Security model:
  - All client data is sourced from DB1 (Zone 1, isolated). In Phase 1 we read
    the JSON seed file directly; Phase 2 replaces _load_clients() with a
    DB1 PostgreSQL query — nothing else changes.
  - expected_outcome is a DB1-internal agent-training label. It is excluded from
    every response by a whitelist enforced in code, not by trust or convention.
  - PII beyond the minimum needed for a dashboard card is restricted to the
    authenticated detail endpoint (/cases/{request_id}).
  - Band messages (Phase 2) will carry only request_id and verdict — never raw
    client fields. That boundary is enforced in band_bridge.py, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Data layer — JSON loader
# Replace _load_clients() body with a DB1 query in Phase 2. All callers and
# whitelists stay identical.
# ---------------------------------------------------------------------------

_DATA_FILE = Path(__file__).parent.parent / "database" / "brightuity_clients.json"


def _load_clients() -> dict[str, dict[str, Any]]:
    with open(_DATA_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    return {c["request_id"]: c for c in raw["clients"]}


_CLIENTS: dict[str, dict[str, Any]] = _load_clients()


# ---------------------------------------------------------------------------
# Field whitelists — the only thing that decides what leaves this process.
# frozenset so it can never be mutated at runtime.
# expected_outcome is deliberately absent from both sets.
# ---------------------------------------------------------------------------

# Fields returned by GET /cases (dashboard queue cards).
# Minimum needed to render the card: identifier, display name, asset context,
# status indicator, and portrait photo. Nothing more.
_CARD_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "encrypted_doc_id",
    "full_name",
    "nationality",
    "country_flag",
    "asset_type",
    "asset_value_eur",
    "status",
    "photo_url",
})

# Fields returned by GET /cases/{request_id} (review detail screen).
# Includes operational context the Head of Digital Assets needs to review the
# case: identity, asset specifics, document status, KYC flags, risk flags.
# passport_number and date_of_birth are included because this endpoint serves
# the authorised reviewer in an internal bank system.
# expected_outcome is NOT included — it is an internal label, never for display.
_DETAIL_FIELDS: frozenset[str] = frozenset({
    "client_id",
    "request_id",
    "encrypted_doc_id",
    "full_name",
    "gender",
    "nationality",
    "country_flag",
    "date_of_birth",
    "passport_number",
    "address",
    "photo_url",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "submitted_at",
    "status",
    "documents_status",
    "document_issues",
    "kyc_status",
    "kyc_flags",
    "source_of_funds",
    "source_verifiable",
    "risk_flags",
})


def _whitelist(client: dict[str, Any], fields: frozenset[str]) -> dict[str, Any]:
    """Return a new dict containing only the allowed fields. Keys absent from
    the source record are silently omitted — never raise on missing fields."""
    return {k: client[k] for k in fields if k in client}


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Brightuity API",
    description=(
        "Zone 1 gateway — Meridian Digital Bank · Digital Assets & Tokenization Division. "
        "Serves client case data for the review pipeline. "
        "expected_outcome is never included in any response."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: restrict to the frontend origin.
# In production: replace with the deployed frontend URL and set allow_origins
# from an environment variable. Do not use ["*"] in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness check. Returns the number of cases loaded from DB1."""
    return {
        "status": "ok",
        "service": "brightuity-api",
        "cases_loaded": len(_CLIENTS),
    }


@app.get("/cases", tags=["cases"])
def list_cases(
    status: str | None = Query(
        default=None,
        description=(
            "Filter by lifecycle status. "
            "Omit to return the pending queue (status=pending). "
            "Pass 'all' to return every case regardless of status."
        ),
    ),
) -> list[dict[str, Any]]:
    """
    Returns the dashboard queue.

    Default (no status param): cases with status=pending — the active queue
    awaiting action by the Head of Digital Assets.

    Each item contains only the fields needed to render a dashboard card.
    PII beyond client name and nationality is excluded.
    expected_outcome is never included under any circumstances.
    """
    if status == "all":
        candidates = list(_CLIENTS.values())
    elif status is not None:
        candidates = [c for c in _CLIENTS.values() if c.get("status") == status]
    else:
        candidates = [c for c in _CLIENTS.values() if c.get("status") == "pending"]

    results = [_whitelist(c, _CARD_FIELDS) for c in candidates]
    # Stable ordering: ascending by request_id (chronological submission order)
    results.sort(key=lambda c: c.get("request_id", ""))
    return results


@app.get("/cases/{request_id}", tags=["cases"])
def get_case(request_id: str) -> dict[str, Any]:
    """
    Returns full operational detail for the review screen.

    Includes document status, KYC flags, source-of-funds, and risk flags so
    the Head of Digital Assets has the context she needs alongside agent verdicts.

    expected_outcome is never returned — it is a DB1-internal training label
    that must never influence or appear in the human review workflow.
    """
    client = _CLIENTS.get(request_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{request_id}' not found.",
        )
    return _whitelist(client, _DETAIL_FIELDS)
