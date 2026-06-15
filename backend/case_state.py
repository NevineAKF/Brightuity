"""
backend/case_state.py
Brightuity — Case lifecycle state machine.

A tokenization review case moves through a fixed set of states.
This module is the single source of truth for which transitions are legal.
All status writes go through validate_transition() first — invalid moves
raise InvalidTransitionError before touching the database.

State diagram:
    pending
      │  (POST /cases/{id}/run)
      ▼
    processing
      │  (pipeline finishes)
      ├──▶ awaiting_decision   (approved_pending_human — all gates cleared)
      ├──▶ halted              (halted_kyc — PEP/AML hard stop)
      ├──▶ blocked_gate        (a compliance gate returned non-pass)
      └──▶ error               (unhandled pipeline exception)

    awaiting_decision
      ├──▶ authorized          (Head of Digital Assets approves — Phase 2)
      └──▶ rejected            (Head of Digital Assets rejects  — Phase 2)

    error ──▶ pending          (explicit retry via force=true re-run)

    authorized, rejected, halted, blocked_gate: TERMINAL — no outward transitions.
"""

from __future__ import annotations

# ── States ────────────────────────────────────────────────────────────────────

ALLOWED_STATES: frozenset[str] = frozenset({
    "pending",            # case exists; pipeline not yet run
    "processing",         # pipeline is running in the background
    "awaiting_decision",  # pipeline approved_pending_human; head must decide
    "authorized",         # Head of Digital Assets approved   [terminal]
    "rejected",           # Head of Digital Assets rejected   [terminal]
    "halted",             # pipeline halted_kyc (PEP/AML)     [terminal]
    "blocked_gate",       # a compliance gate blocked the seal [terminal]
    "error",              # pipeline raised an unhandled exception
})

# ── Transition table ──────────────────────────────────────────────────────────

_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending":           frozenset({"processing"}),
    "processing":        frozenset({"awaiting_decision", "halted", "blocked_gate", "error"}),
    "awaiting_decision": frozenset({"authorized", "rejected"}),
    "authorized":        frozenset(),
    "rejected":          frozenset(),
    "halted":            frozenset(),
    "blocked_gate":      frozenset(),
    "error":             frozenset({"pending"}),  # explicit retry only
}

# ── Orchestrator → case status mapping ───────────────────────────────────────

_PIPELINE_STATUS_MAP: dict[str, str] = {
    "approved_pending_human": "awaiting_decision",
    "halted_kyc":             "halted",
    "blocked_gate":           "blocked_gate",
    "error":                  "error",
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class InvalidTransitionError(Exception):
    """Raised when a requested state transition is not in the transition table."""


# ── Public interface ──────────────────────────────────────────────────────────

def validate_transition(from_state: str, to_state: str) -> None:
    """
    Assert that from_state → to_state is a permitted transition.

    Raises InvalidTransitionError (not ValueError) so callers can catch it
    specifically without catching every programming mistake.
    """
    if from_state not in _TRANSITIONS:
        raise InvalidTransitionError(
            f"Unknown state '{from_state}'. "
            f"Valid states: {sorted(ALLOWED_STATES)}."
        )
    allowed: frozenset[str] = _TRANSITIONS[from_state]
    if to_state not in allowed:
        human_allowed = sorted(allowed) if allowed else ["(none — terminal state)"]
        raise InvalidTransitionError(
            f"Transition '{from_state}' → '{to_state}' is not permitted. "
            f"Allowed transitions from '{from_state}': {human_allowed}."
        )


def pipeline_status_to_case_status(pipeline_status: str) -> str:
    """
    Convert orchestrator pipeline_status to a case lifecycle status.

    Unknown pipeline_status values map to 'error' so failures are visible
    rather than silently disappearing into an unknown state.
    """
    return _PIPELINE_STATUS_MAP.get(pipeline_status, "error")


def is_terminal(status: str) -> bool:
    """Return True if status has no outward transitions (case is closed)."""
    return not bool(_TRANSITIONS.get(status))


def is_active(status: str) -> bool:
    """Return True if the pipeline is currently running for this case."""
    return status == "processing"


def can_run(status: str, *, force: bool = False) -> tuple[bool, str]:
    """
    Determine whether a new pipeline run is permitted given the current status.

    Returns (allowed: bool, reason: str).
    reason is empty when allowed=True.

    force=True unlocks re-run from: awaiting_decision, halted, blocked_gate, error.
    force=True does NOT unlock re-run from: processing (can't run two in parallel).
    force=True does NOT unlock re-run from terminal human-decision states:
        authorized, rejected (a new case must be created to re-evaluate).
    """
    if status == "pending":
        return True, ""

    if status == "processing":
        return False, (
            "Pipeline is already running for this case. "
            "Wait for it to complete before re-running."
        )

    if status in ("authorized", "rejected"):
        return False, (
            f"Case is in terminal state '{status}' (human decision recorded). "
            "Create a new case to initiate a fresh review."
        )

    if force:
        # awaiting_decision, halted, blocked_gate, error → allow force re-run
        return True, ""

    return False, (
        f"Case is already in state '{status}'. "
        "Pass force=true to explicitly re-run the pipeline."
    )
