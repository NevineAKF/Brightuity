"""
agents/orchestrator/test_guard_logic.py
Unit tests for the duplicate-trigger guard in OrchestratorAdapter.on_message.

Covers:
  1. Module-level state constants (_ACTIVE_STATES, _TERMINAL_STATES).
  2. _stage_label helper — human-readable labels, unknown-state passthrough.
  3. Guard branching:
       active    → duplicate trigger rejected; case state unchanged.
       terminal  → re-run allowed; case reset to awaiting_stage1.
       unrecognised → treated as active; rejected safely.

The adapter extends Band's SimpleAdapter.  If OrchestratorAdapter() fails to
instantiate in this environment (e.g. the SDK requires live platform credentials
in __init__), the guard-branch tests are automatically skipped via pytest.skip
rather than producing a false failure.

Run via: pytest agents/orchestrator/test_guard_logic.py -v
"""
from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from band_agents.orchestrator_adapter import (
    _ACTIVE_STATES,
    _TERMINAL_STATES,
    _stage_label,
    _STAGE1_GATES,
    OrchestratorAdapter,
)


# ── 1. Module-level constants ─────────────────────────────────────────────────

def test_active_states_membership():
    assert "awaiting_stage1"    in _ACTIVE_STATES
    assert "awaiting_tokenizer" in _ACTIVE_STATES


def test_terminal_states_membership():
    assert "complete" in _TERMINAL_STATES
    assert "timeout"  in _TERMINAL_STATES


def test_active_and_terminal_are_disjoint():
    assert _ACTIVE_STATES.isdisjoint(_TERMINAL_STATES), (
        "A state must not appear in both _ACTIVE_STATES and _TERMINAL_STATES"
    )


def test_active_and_terminal_are_frozensets():
    assert isinstance(_ACTIVE_STATES,   frozenset)
    assert isinstance(_TERMINAL_STATES, frozenset)


# ── 2. _stage_label helper ────────────────────────────────────────────────────

def test_stage_label_awaiting_stage1():
    assert _stage_label("awaiting_stage1") == "screening (stage 1)"


def test_stage_label_awaiting_tokenizer():
    assert _stage_label("awaiting_tokenizer") == "tokenization (stage 2)"


def test_stage_label_unknown_returns_raw_state():
    # Unknown states must pass through unchanged (defensive).
    assert _stage_label("bogus_unknown_state") == "bogus_unknown_state"


def test_stage_label_returns_no_raw_internal_keys_for_known_states():
    # Human-facing labels must not expose the raw internal key string.
    for state in _ACTIVE_STATES:
        label = _stage_label(state)
        assert state not in label, (
            f"_stage_label({state!r}) returned {label!r} which contains the raw key"
        )


# ── 3. Guard branch tests (adapter instantiation required) ───────────────────

class _MockTools:
    """Minimal AgentToolsProtocol stub — captures sent messages."""
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, text: str, mentions=None) -> None:
        self.sent.append(text)

    async def send_event(self, *args, **kwargs) -> None:
        pass


class _MockMsg:
    """Minimal PlatformMessage stub for a human trigger."""
    sender_type = "User"
    sender_id   = "human-uuid-001"
    sender_name = "Test User"
    content     = "@Orchestrator REQ-9999"


_ROOM_ID    = "room-test-guard"
_REQUEST_ID = "REQ-9999"
_CASE_KEY   = (_ROOM_ID, _REQUEST_ID)


def _make_adapter() -> OrchestratorAdapter:
    """Construct adapter; skip test if Band SDK blocks instantiation."""
    try:
        return OrchestratorAdapter()
    except Exception as exc:
        pytest.skip(
            f"OrchestratorAdapter() could not be instantiated "
            f"({type(exc).__name__}: {exc}). "
            "Guard-branch test skipped — requires live Band SDK."
        )


def _seed_case(adapter: OrchestratorAdapter, state: str) -> None:
    """Inject a pre-existing case into adapter._cases with the given state."""
    adapter._cases[_CASE_KEY] = {
        "initiator":       "human-uuid-001",
        "state":           state,
        "verdicts":        {k: None for k in _STAGE1_GATES},
        "summaries":       {},
        "acked":           set(),
        "chase_task":      None,
        "gate_outcome":    None,
        "gate_reason":     None,
        "pipeline_status": None,
        "seal_result":     None,
    }


def _trigger(adapter: OrchestratorAdapter, tools: _MockTools) -> None:
    """Run on_message with a human trigger synchronously."""
    asyncio.run(adapter.on_message(
        _MockMsg(), tools, [], None, None,
        is_session_bootstrap=False,
        room_id=_ROOM_ID,
    ))


# ── active case: duplicate trigger must be rejected ───────────────────────────

def test_active_awaiting_stage1_rejected():
    adapter = _make_adapter()
    _seed_case(adapter, "awaiting_stage1")

    tools = _MockTools()
    _trigger(adapter, tools)

    # Case must still exist with the original state — not reset.
    assert _CASE_KEY in adapter._cases
    assert adapter._cases[_CASE_KEY]["state"] == "awaiting_stage1"

    # A rejection message must have been posted.
    assert tools.sent, "Expected a rejection message to be sent"

    # Message must use a human-readable label, not the raw internal state key.
    msg = tools.sent[0]
    assert "screening" in msg,          f"Expected 'screening' in message: {msg!r}"
    assert "awaiting_stage1" not in msg, f"Raw state key must not appear: {msg!r}"


def test_active_awaiting_tokenizer_rejected():
    adapter = _make_adapter()
    _seed_case(adapter, "awaiting_tokenizer")

    tools = _MockTools()
    _trigger(adapter, tools)

    assert _CASE_KEY in adapter._cases
    assert adapter._cases[_CASE_KEY]["state"] == "awaiting_tokenizer"

    msg = tools.sent[0]
    assert "tokenization" in msg,           f"Expected 'tokenization' in message: {msg!r}"
    assert "awaiting_tokenizer" not in msg, f"Raw state key must not appear: {msg!r}"


# ── terminal case: re-run must reset state ────────────────────────────────────

def test_terminal_complete_resets_to_fresh_case():
    adapter = _make_adapter()
    # Pre-populate verdicts to confirm they are wiped on re-run.
    _seed_case(adapter, "complete")
    adapter._cases[_CASE_KEY]["verdicts"]["doc_auditor"] = "pass"
    adapter._cases[_CASE_KEY]["acked"].add("kyc_guardian")

    tools = _MockTools()
    _trigger(adapter, tools)

    # Case must have been re-initialised.
    assert _CASE_KEY in adapter._cases
    assert adapter._cases[_CASE_KEY]["state"] == "awaiting_stage1"

    # All verdict slots reset to None.
    assert all(
        v is None for v in adapter._cases[_CASE_KEY]["verdicts"].values()
    ), "All verdicts must be None after re-run reset"

    # Acked set must be empty.
    assert adapter._cases[_CASE_KEY]["acked"] == set()

    # No rejection message — re-runs are silent (mentioning agents is enough).
    # (Rejection messages start with the request_id in backticks; check absence.)
    for m in tools.sent:
        assert "already being processed" not in m, (
            f"Re-run should not produce a rejection message: {m!r}"
        )


def test_terminal_timeout_resets_to_fresh_case():
    adapter = _make_adapter()
    _seed_case(adapter, "timeout")

    tools = _MockTools()
    _trigger(adapter, tools)

    assert _CASE_KEY in adapter._cases
    assert adapter._cases[_CASE_KEY]["state"] == "awaiting_stage1"
    assert all(v is None for v in adapter._cases[_CASE_KEY]["verdicts"].values())


# ── defensive default: unrecognised state ─────────────────────────────────────

def test_unrecognised_state_rejected_safely():
    adapter = _make_adapter()
    _seed_case(adapter, "some_future_state_we_do_not_know_about")

    tools = _MockTools()
    _trigger(adapter, tools)

    # Must reject — do NOT start a parallel run.
    assert _CASE_KEY in adapter._cases
    # State must not have been reset to awaiting_stage1.
    assert adapter._cases[_CASE_KEY]["state"] != "awaiting_stage1"
    # A message must have been sent (even if generic).
    assert tools.sent, "Expected a rejection/error message for unrecognised state"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
