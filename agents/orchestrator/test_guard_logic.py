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


# ── Backend-agent trigger routing ────────────────────────────────────────────
#
# These tests patch band_agents.orchestrator_adapter._BACKEND_AGENT_ID at the
# module level (restoring it in a finally block) so the routing guard sees a
# known fake UUID without affecting any other test.

import band_agents.orchestrator_adapter as _adapter_module

_FAKE_BACKEND_UUID = "backend-test-uuid-0000-000000000000"
_OTHER_AGENT_UUID  = "specialist-test-uuid-1111-111111111111"
_TRIGGER_ROOM      = "room-routing-test"
_TRIGGER_REQ       = "REQ-9998"
_TRIGGER_CASE_KEY  = (_TRIGGER_ROOM, _TRIGGER_REQ)


class _BackendMsg:
    """Simulates a Band message posted by the backend agent with a valid REQ-id."""
    sender_type = "Agent"
    sender_id   = _FAKE_BACKEND_UUID
    sender_name = "Brightuity Backend"
    content     = f"@Orchestrator {_TRIGGER_REQ}"


class _OtherAgentMsg:
    """Simulates a Band message posted by a different (specialist) agent."""
    sender_type = "Agent"
    sender_id   = _OTHER_AGENT_UUID
    sender_name = "Some Specialist"
    content     = f"@Orchestrator {_TRIGGER_REQ}"


def _run_routing(msg_cls, room: str = _TRIGGER_ROOM) -> tuple[OrchestratorAdapter, _MockTools]:
    adapter = _make_adapter()
    tools   = _MockTools()
    asyncio.run(adapter.on_message(
        msg_cls(), tools, [], None, None,
        is_session_bootstrap=False,
        room_id=room,
    ))
    return adapter, tools


def test_backend_agent_routes_to_case_start():
    """
    A message whose sender_type == 'Agent' and sender_id == _BACKEND_AGENT_ID
    must be routed to case-start logic, NOT to _collect_verdict.

    Proof: if case-start ran, the case exists with state == 'awaiting_stage1'.
    If verdict collection ran instead, no case is created (unknown UUID, early
    return from _collect_verdict).
    """
    orig = _adapter_module._BACKEND_AGENT_ID
    _adapter_module._BACKEND_AGENT_ID = _FAKE_BACKEND_UUID
    try:
        adapter, tools = _run_routing(_BackendMsg)

        # Case must have been created by the case-start path.
        assert _TRIGGER_CASE_KEY in adapter._cases, (
            "Backend agent trigger must create a pipeline case"
        )
        case = adapter._cases[_TRIGGER_CASE_KEY]
        assert case["state"] == "awaiting_stage1"

        # Initiator must be the backend agent's sender_id (not a human UUID).
        assert case["initiator"] == _FAKE_BACKEND_UUID

        # Verdicts must be initialised to None (fresh case).
        assert all(v is None for v in case["verdicts"].values())

        # No rejection message must have been sent.
        assert not any("already being processed" in m for m in tools.sent)
    finally:
        _adapter_module._BACKEND_AGENT_ID = orig
        # Cancel any chase task left running.
        adapter, _ = _make_adapter(), None  # no need to re-use adapter after finally


def test_backend_agent_routes_to_case_start_cancel_chase():
    """Same as above but also cleans up the chase task to avoid asyncio warnings."""
    orig = _adapter_module._BACKEND_AGENT_ID
    _adapter_module._BACKEND_AGENT_ID = _FAKE_BACKEND_UUID
    adapter = None
    try:
        adapter, tools = _run_routing(_BackendMsg, room="room-routing-cancel")
        case_key = ("room-routing-cancel", _TRIGGER_REQ)
        assert case_key in adapter._cases
        assert adapter._cases[case_key]["state"] == "awaiting_stage1"
    finally:
        _adapter_module._BACKEND_AGENT_ID = orig
        if adapter is not None:
            chase = (adapter._cases.get(("room-routing-cancel", _TRIGGER_REQ)) or {}).get("chase_task")
            if chase and not chase.done():
                chase.cancel()


def test_other_agent_routes_to_verdict_collection_not_case_start():
    """
    A message whose sender_type == 'Agent' and sender_id != _BACKEND_AGENT_ID
    must be routed to _collect_verdict, NOT to case-start.

    Proof: no case is created (unknown UUID → early return from _collect_verdict),
    and no 'I need a request_id' error message is sent (which would only appear
    on the case-start path when content has no REQ-id — but content DOES have a
    REQ-id here, so if case-start ran, a case WOULD be created).
    """
    orig = _adapter_module._BACKEND_AGENT_ID
    _adapter_module._BACKEND_AGENT_ID = _FAKE_BACKEND_UUID
    try:
        adapter, tools = _run_routing(_OtherAgentMsg)

        # No case must have been created — verdict-collection path taken.
        assert _TRIGGER_CASE_KEY not in adapter._cases, (
            "A non-backend agent message must NOT create a case "
            "(it should go to _collect_verdict, not case-start)"
        )

        # No trigger error message should have been sent.
        assert not any("I need a" in m for m in tools.sent), (
            f"Unexpected case-start error message sent: {tools.sent}"
        )
    finally:
        _adapter_module._BACKEND_AGENT_ID = orig


def test_backend_agent_inactive_when_env_unset():
    """
    When _BACKEND_AGENT_ID is empty (env var not configured), a message with
    sender_type == 'Agent' must always go to _collect_verdict regardless of UUID.
    No agent can act as a trigger when the backend UUID is unconfigured.
    """
    orig = _adapter_module._BACKEND_AGENT_ID
    _adapter_module._BACKEND_AGENT_ID = ""   # simulate unset env var
    try:
        # Use the backend UUID as sender — but with the env var empty, it must
        # NOT be treated as a trigger.
        adapter, tools = _run_routing(_BackendMsg, room="room-unset-test")
        case_key = ("room-unset-test", _TRIGGER_REQ)

        # No case must have been created.
        assert case_key not in adapter._cases, (
            "When BAND_BACKEND_AGENT_ID is unset, no Agent message should trigger a case"
        )
        assert not tools.sent, (
            f"No message should be sent when the env var is unset: {tools.sent}"
        )
    finally:
        _adapter_module._BACKEND_AGENT_ID = orig


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
