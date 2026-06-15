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
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend import case_state, case_store
from agents.orchestrator.orchestrator import run_pipeline
from agents.governance_audit.logic import assemble_evidence_package

logger = logging.getLogger(__name__)

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
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI):
    case_store.init_db()
    yield


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
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS: restrict to the frontend origin.
# In production: replace with the deployed frontend URL and set allow_origins
# from an environment variable. Do not use ["*"] in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Pipeline background task
# ---------------------------------------------------------------------------

def _run_pipeline_bg(
    request_id: str,
    client_record: dict[str, Any],
    agent_overrides: dict | None,
    synthesis_override: Any,
) -> None:
    """
    Execute the full pipeline in a background thread.

    Called by BackgroundTasks after the POST /cases/{id}/run response is sent.
    Writes the result to the case store and advances the case status.

    # ── Phase 2 Band live-streaming hook ───────────────────────────────────
    # After each agent completes, the orchestrator emits events into event_log.
    # Phase 2: iterate event_log here and forward each event to the Band room
    # for this request_id via band_bridge.post_event(request_id, event).
    # That delivers real-time @mentions to the Head of Digital Assets as each
    # gate clears or fails — before the pipeline finishes.
    # ───────────────────────────────────────────────────────────────────────
    """
    try:
        decision_record, event_log = run_pipeline(
            client_record,
            _agent_overrides=agent_overrides or {},
            _synthesis_override=synthesis_override,
        )
        evidence_package = assemble_evidence_package(
            decision_record, event_log, client_record
        )
        case_store.save_pipeline_result(request_id, decision_record, evidence_package)

        new_status = case_state.pipeline_status_to_case_status(
            decision_record.get("pipeline_status", "error")
        )
        case_store.set_status(request_id, new_status)

    except Exception as exc:
        logger.error(
            "pipeline background task failed for %s: %s", request_id, exc, exc_info=True
        )
        case_store.set_status(request_id, "error")


# ---------------------------------------------------------------------------
# Injectable pipeline overrides (dependency injection seam for testing)
#
# Production: both functions return None → run_pipeline uses real LLM agents.
# Tests: override via app.dependency_overrides to inject mock agents/synthesis
# without any real LLM calls. This seam must never be removed.
# ---------------------------------------------------------------------------

def _pipeline_agent_overrides() -> dict | None:
    """Agent override dict for run_pipeline. None = use real LLM agents."""
    return None


def _pipeline_synthesis_override() -> Any:
    """Synthesis override callable for run_pipeline. None = use real synthesis."""
    return None


# ---------------------------------------------------------------------------
# Endpoints — existing (unchanged)
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


# ---------------------------------------------------------------------------
# Endpoints — pipeline execution + status (new)
# ---------------------------------------------------------------------------

@app.post(
    "/cases/{request_id}/run",
    status_code=202,
    tags=["pipeline"],
    summary="Trigger the compliance pipeline for a case",
)
async def run_case(
    request_id: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(
        default=False,
        description=(
            "Re-run the pipeline even if a prior run exists. "
            "Requires case to be in a re-runnable state "
            "(awaiting_decision, halted, blocked_gate, error). "
            "Never allowed while the pipeline is already running (status=processing)."
        ),
    ),
    agent_overrides: dict | None = Depends(_pipeline_agent_overrides),
    synthesis_override: Any = Depends(_pipeline_synthesis_override),
) -> dict[str, Any]:
    """
    Kick off the 8-agent compliance pipeline for a client case.

    Returns 202 Accepted immediately. The pipeline runs in a background thread
    (~60-90 s for real LLM agents). Poll GET /cases/{id}/status for completion.

    State machine:
      pending           → processing (first run, no force needed)
      awaiting_decision → processing (re-run, requires force=true)
      halted            → processing (re-run, requires force=true)
      blocked_gate      → processing (re-run, requires force=true)
      error             → processing (retry, requires force=true)
      processing        → 409 Conflict (pipeline already running)
      authorized/rejected → 409 Conflict (terminal; create a new case)
    """
    # 1. Verify the client exists in Zone 1
    client_record = _CLIENTS.get(request_id)
    if client_record is None:
        raise HTTPException(status_code=404, detail=f"Client '{request_id}' not found.")

    # 2. Look up (or create) the case record in the DB
    case = case_store.get_case(request_id)
    if case is None:
        try:
            case = case_store.create_case_record(request_id, status="pending")
        except sqlite3.IntegrityError:
            # Race condition: another request created it first
            case = case_store.get_case(request_id)

    current_status = case["status"]

    # 3. Check whether a run is permitted
    allowed, reason = case_state.can_run(current_status, force=force)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)

    # 4. If force re-run: directly reset to pending.
    # force=True explicitly authorises bypassing the normal transition table for this
    # reset step — that is the semantic of "force". The next step (pending→processing)
    # is validated normally.
    if current_status != "pending":
        case_store.set_status(request_id, "pending")

    # 5. Transition: pending → processing
    case_state.validate_transition("pending", "processing")
    case_store.set_status(request_id, "processing")

    # 6. Launch background task — response is sent immediately after this
    background_tasks.add_task(
        _run_pipeline_bg,
        request_id,
        client_record,
        agent_overrides,
        synthesis_override,
    )

    return {
        "request_id": request_id,
        "status":     "processing",
        "message":    (
            "Pipeline started. Poll GET /cases/{request_id}/status for completion. "
            "Typical runtime: 60-90 s with real LLM agents."
        ),
    }


@app.get(
    "/cases/{request_id}/status",
    tags=["pipeline"],
    summary="Poll pipeline and case lifecycle status",
)
def case_status(request_id: str) -> dict[str, Any]:
    """
    Return the current lifecycle status and pipeline outcome for a case.

    pipeline_status, gate_outcome, seal_status, and consensus_hash are
    populated once the pipeline completes; null while still processing.
    """
    if _CLIENTS.get(request_id) is None:
        raise HTTPException(status_code=404, detail=f"Client '{request_id}' not found.")

    case = case_store.get_case(request_id)
    if case is None:
        return {
            "request_id":      request_id,
            "status":          "pending",
            "pipeline_status": None,
            "gate_outcome":    None,
            "seal_status":     None,
            "consensus_hash":  None,
            "initiated_at":    None,
            "updated_at":      None,
        }

    return {
        "request_id":      case["request_id"],
        "status":          case["status"],
        "pipeline_status": case.get("pipeline_status"),
        "gate_outcome":    case.get("gate_outcome"),
        "seal_status":     case.get("seal_status"),
        "consensus_hash":  case.get("consensus_hash"),
        "initiated_at":    case.get("initiated_at"),
        "updated_at":      case.get("updated_at"),
    }


@app.get(
    "/cases/{request_id}/package",
    tags=["pipeline"],
    summary="Retrieve the assembled Evidence Package",
)
def case_package(request_id: str) -> dict[str, Any]:
    """
    Return the full Decision Evidence Package for a completed case.

    This is the primary output of the Brightuity compliance pipeline:
    an 8-section auditable record including agent verdicts, KYC watchlist
    provenance, deterministic risk metrics, ECDSA consensus seal, and the
    Layer 2 human-readable briefing.

    Returns 404 if the case doesn't exist.
    Returns 202 if the pipeline hasn't completed yet.
    """
    if _CLIENTS.get(request_id) is None:
        raise HTTPException(status_code=404, detail=f"Client '{request_id}' not found.")

    pkg = case_store.get_evidence_package(request_id)
    if pkg is None:
        # Case exists but pipeline hasn't completed
        case = case_store.get_case(request_id)
        status = case["status"] if case else "pending"
        raise HTTPException(
            status_code=202,
            detail=(
                f"Evidence package not yet available. "
                f"Current status: '{status}'. "
                f"Poll GET /cases/{request_id}/status for completion."
            ),
        )
    return pkg
