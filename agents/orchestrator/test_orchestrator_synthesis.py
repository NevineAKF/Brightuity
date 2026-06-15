"""
agents/orchestrator/test_orchestrator_synthesis.py
Brightuity — Orchestrator Layer 2 synthesis test.

Proves the LLM synthesis layer (Layer 2) behaviour in isolation via mocks.
No real LLM calls. All agent functions AND the synthesizer are injected mocks.

Architecture reminder:
  Layer 1 (deterministic): gates + ECDSA seal — already proven 37/37.
  Layer 2 (additive):      Claude Opus 4.8 reads the SEALED decision_record
                           and writes the briefing. ZERO authority over decisions.
                           If synthesis fails → deterministic templated fallback.

Three paths covered:
  1. LLM success  — synthesize_briefing called, returns LLM result; briefing
                    attached to decision_record; Layer 1 fields untouched.
  2. LLM failure  — call_agent_model raises ModelUnavailableError inside
                    synthesis.py; synthesize_briefing catches it and returns
                    templated_fallback; pipeline still completes normally.
  3. Halt path    — pipeline_status=halted_kyc; LLM forced to fail (templated);
                    briefing still produced; headline reflects halt; recommend-
                    ation defers to human; Layer 1 fields not altered.

Additional invariant checked across all three paths:
  Layer 2 must NEVER alter pipeline_status, gate_outcome, or seal.

Run:
    python -m agents.orchestrator.test_orchestrator_synthesis
  or:
    python agents/orchestrator/test_orchestrator_synthesis.py
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Suppress INFO during test — only WARNING+ to stderr.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

from agents.orchestrator.orchestrator import run_pipeline
from shared.call_agent_model import ModelUnavailableError

# ── Symbols ────────────────────────────────────────────────────────────────────
_OK   = "✓"
_FAIL = "✗"
_SEP  = "─" * 70
_SEP2 = "═" * 70


# ── Mock client record ─────────────────────────────────────────────────────────
_MOCK_RECORD: dict = {
    "request_id":      "REQ-TEST-SYNTH",
    "client_id":       "CLT-SYNTH",
    "asset_type":      "Commercial Property",
    "asset_value_eur": 2_000_000,
    "submitted_at":    "2026-06-15T00:00:00",
    "full_name":       "Synthesis Test User",
    "nationality":     "Germany",
    "asset_detail":    "Test asset for synthesis layer",
    "risk_flags":      [],
}


# ── Mock agent constructors ───────────────────────────────────────────────────

def _v(agent: str, verdict: str, **extra) -> dict:
    return {
        "agent":        agent,
        "verdict":      verdict,
        "summary":      f"Mock {verdict} verdict for {agent}.",
        "model_used":   "mock",
        "was_fallback": False,
        "latency_ms":   1,
        **extra,
    }


def _doc_pass(r):  return _v("doc_auditor", "pass", issues_found=[])
def _kyc_pass(r):  return _v("kyc_guardian", "pass", flags_raised=[])
def _kyc_halt(r):  return _v("kyc_guardian", "halt",
                              summary="PEP match confirmed — pipeline HALT.",
                              flags_raised=["pep_match"])
def _comp_pass(r): return _v("dynamic_compliance", "pass",
                              jurisdiction="EU", citations=[], concerns=[], retrieved_k=0)
def _stress_pass(r): return _v("stress_test", "pass", risk_level="low", risk_factors=[])
def _token_pass(r):  return _v("asset_tokenizer", "pass",
                                token_standard="ERC-3643 T-REX",
                                total_tokens=1_000,
                                value_per_token_eur=2_000.0,
                                structure_notes=["QI only"])

_ALL_PASS_OVERRIDES = {
    "doc_auditor":        _doc_pass,
    "kyc_guardian":       _kyc_pass,
    "dynamic_compliance": _comp_pass,
    "stress_test":        _stress_pass,
    "asset_tokenizer":    _token_pass,
}

_KYC_HALT_OVERRIDES = {
    "doc_auditor":        _doc_pass,
    "kyc_guardian":       _kyc_halt,
    "dynamic_compliance": _comp_pass,
    "stress_test":        _stress_pass,
    "asset_tokenizer":    _token_pass,
}

# ── Assertion tracker ──────────────────────────────────────────────────────────

_failures: list[str] = []
_total:    list[None] = []


def _check(label: str, condition: bool, got=None) -> None:
    _total.append(None)
    suffix = f"  [{got}]" if got is not None else ""
    if condition:
        print(f"    {_OK}  {label}{suffix}")
    else:
        detail = f"  (got: {got!r})" if got is not None else ""
        print(f"    {_FAIL}  FAIL: {label}{detail}")
        _failures.append(label)


# ── Invariant helper: verify Layer 1 fields untouched ─────────────────────────

def _check_layer1_untouched(
    decision:          dict,
    expected_status:   str,
    expected_gate:     str,
    expected_seal_st:  str,
    test_label:        str,
) -> None:
    """Verify Layer 2 did not alter any Layer 1 field."""
    _check(f"[{test_label}] pipeline_status not altered by Layer 2",
           decision["pipeline_status"] == expected_status,
           got=decision["pipeline_status"])
    _check(f"[{test_label}] gate_outcome not altered by Layer 2",
           decision["gate_outcome"] == expected_gate,
           got=decision["gate_outcome"])
    seal = decision.get("seal") or {}
    _check(f"[{test_label}] seal.status not altered by Layer 2",
           seal.get("status") == expected_seal_st,
           got=seal.get("status"))


# ── Test 1: LLM synthesis success ─────────────────────────────────────────────

def test_synthesis_llm_success() -> None:
    """
    Patch synthesize_briefing to return a mock LLM result.
    Verify: briefing present in decision_record, source="llm", all 4 schema
    fields populated, headline consistent with approved status, briefing_complete
    event emitted, Layer 1 fields untouched.
    """
    print()
    print(_SEP)
    print("  [SYNTH 1]  LLM synthesis success")
    print("             synthesize_briefing returns 'llm' result → attached to decision_record")
    print(_SEP)

    mock_briefing = {
        "headline":
            "APPROVED PENDING HUMAN REVIEW — All five compliance gates cleared; "
            "EUR 2M commercial property tokenisation proposed.",
        "decisive_factor":
            "All mandatory gates passed: documents verified, KYC cleared, "
            "EU compliance confirmed, risk within limits, token structure designed.",
        "per_agent_summary": [
            "Doc Auditor: PASS — all documents verified, ownership chain complete.",
            "KYC Guardian: PASS — identity confirmed, no PEP/sanctions hit.",
            "Dynamic Compliance: PASS — MiCA compliant, EU jurisdiction clear.",
            "Stress-Test Simulator: PASS — risk level low, within policy limits.",
            "Asset Tokenizer: PASS — ERC-3643 T-REX, 1,000 tokens × EUR 2,000.",
        ],
        "recommendation":
            "All five mandatory gates cleared and the ECDSA seal was produced. "
            "Recommend the Head of Digital Assets reviews the full decision record "
            "and proposed token structure before issuing a final Approve or Reject.",
        "source":       "llm",
        "model_used":   "claude-opus-4-8",
        "was_fallback": False,
        "latency_ms":   3_200,
    }

    with patch("agents.orchestrator.orchestrator.synthesize_briefing") as mock_synth:
        mock_synth.return_value = mock_briefing

        decision, events = run_pipeline(
            _MOCK_RECORD,
            _agent_overrides=_ALL_PASS_OVERRIDES,
        )

    briefing = decision.get("briefing")

    _check("decision_record['briefing'] present",
           briefing is not None, got=type(briefing).__name__)
    _check("briefing['source'] = 'llm'",
           briefing.get("source") == "llm", got=briefing.get("source"))
    _check("briefing['headline'] non-empty str",
           isinstance(briefing.get("headline"), str) and len(briefing.get("headline", "")) > 0,
           got=briefing.get("headline", "")[:60] + "...")
    _check("briefing['decisive_factor'] non-empty str",
           isinstance(briefing.get("decisive_factor"), str) and len(briefing.get("decisive_factor", "")) > 0,
           got=briefing.get("decisive_factor", "")[:50] + "...")
    _check("briefing['per_agent_summary'] is list with ≥ 1 entry",
           isinstance(briefing.get("per_agent_summary"), list)
           and len(briefing.get("per_agent_summary", [])) >= 1,
           got=f"{len(briefing.get('per_agent_summary', []))} entries")
    _check("briefing['recommendation'] non-empty str",
           isinstance(briefing.get("recommendation"), str) and len(briefing.get("recommendation", "")) > 0,
           got=briefing.get("recommendation", "")[:50] + "...")
    _check("briefing['model_used'] = 'claude-opus-4-8'",
           briefing.get("model_used") == "claude-opus-4-8",
           got=briefing.get("model_used"))
    _check("briefing['was_fallback'] = False",
           briefing.get("was_fallback") is False,
           got=briefing.get("was_fallback"))

    # Headline must not contradict the pipeline status
    headline_lower = briefing.get("headline", "").lower()
    _check("headline consistent with approved status (contains 'approved' or 'pending' or 'review')",
           any(w in headline_lower for w in ("approved", "pending", "review", "cleared")),
           got=briefing.get("headline", "")[:60])

    # briefing_complete event in the log
    bc_events = [e for e in events if e["event"] == "briefing_complete"]
    _check("'briefing_complete' event emitted",
           len(bc_events) == 1, got=f"{len(bc_events)} event(s)")
    _check("briefing_complete.source = 'llm'",
           bc_events[0].get("source") == "llm" if bc_events else False,
           got=bc_events[0].get("source") if bc_events else "missing")

    # synthesize_briefing was called exactly once with the decision_record
    _check("synthesize_briefing called exactly once",
           mock_synth.call_count == 1, got=mock_synth.call_count)

    _check_layer1_untouched(
        decision,
        expected_status="approved_pending_human",
        expected_gate="pass",
        expected_seal_st="sealed",
        test_label="SYNTH 1",
    )


# ── Test 2: LLM failure → templated fallback ──────────────────────────────────

def test_synthesis_llm_failure_templated_fallback() -> None:
    """
    Patch call_agent_model inside synthesis.py to raise ModelUnavailableError.
    synthesize_briefing catches it and builds a templated_fallback briefing.
    Verify: pipeline completes normally, source="templated_fallback", all 4
    schema fields present and non-empty, pipeline_status unchanged.
    """
    print()
    print(_SEP)
    print("  [SYNTH 2]  LLM failure → deterministic templated fallback")
    print("             call_agent_model raises ModelUnavailableError →")
    print("             synthesis.py catches it → templated briefing produced")
    print(_SEP)

    with patch("agents.orchestrator.synthesis.call_agent_model") as mock_cam:
        mock_cam.side_effect = ModelUnavailableError(
            agent_name="orchestrator",
            primary="claude-opus-4-8",
            fallback="claude-sonnet-4-6",
            last_error="test-induced unavailability",
        )

        decision, events = run_pipeline(
            _MOCK_RECORD,
            _agent_overrides=_ALL_PASS_OVERRIDES,
        )

    briefing = decision.get("briefing")

    _check("Pipeline completed normally despite LLM failure",
           True, got="returned without crash")
    _check("decision_record['briefing'] present",
           briefing is not None, got=type(briefing).__name__)
    _check("briefing['source'] = 'templated_fallback'",
           briefing.get("source") == "templated_fallback",
           got=briefing.get("source"))
    _check("briefing['model_used'] = 'none'",
           briefing.get("model_used") == "none",
           got=briefing.get("model_used"))
    _check("briefing['headline'] non-empty",
           isinstance(briefing.get("headline"), str) and len(briefing.get("headline", "")) > 0,
           got=briefing.get("headline", "")[:70])
    _check("briefing['decisive_factor'] non-empty",
           isinstance(briefing.get("decisive_factor"), str) and len(briefing.get("decisive_factor", "")) > 0,
           got=briefing.get("decisive_factor", "")[:60])
    _check("briefing['per_agent_summary'] is non-empty list",
           isinstance(briefing.get("per_agent_summary"), list)
           and len(briefing.get("per_agent_summary", [])) >= 1,
           got=f"{len(briefing.get('per_agent_summary', []))} entries")
    _check("briefing['recommendation'] non-empty",
           isinstance(briefing.get("recommendation"), str) and len(briefing.get("recommendation", "")) > 0,
           got=briefing.get("recommendation", "")[:60])

    # briefing_complete event
    bc_events = [e for e in events if e["event"] == "briefing_complete"]
    _check("'briefing_complete' event emitted",
           len(bc_events) == 1, got=f"{len(bc_events)} event(s)")
    _check("briefing_complete.source = 'templated_fallback'",
           bc_events[0].get("source") == "templated_fallback" if bc_events else False,
           got=bc_events[0].get("source") if bc_events else "missing")

    _check_layer1_untouched(
        decision,
        expected_status="approved_pending_human",
        expected_gate="pass",
        expected_seal_st="sealed",
        test_label="SYNTH 2",
    )

    print(f"\n    Templated headline: {briefing.get('headline', '')[:80]}")


# ── Test 3: Halt path with templated briefing ─────────────────────────────────

def test_synthesis_halt_path_templated() -> None:
    """
    KYC halt pipeline path (pipeline_status=halted_kyc).
    LLM forced to fail (ModelUnavailableError) so the templated fallback runs.
    Verify:
      - Briefing is still produced on the halt path (synthesis runs regardless).
      - Headline reflects the KYC halt (contains 'HALT' or similar).
      - Recommendation defers final decision to the human / recommends escalation.
      - pipeline_status = halted_kyc (not altered by Layer 2).
      - gate_outcome = halt (not altered by Layer 2).
      - seal.status = blocked (not altered by Layer 2).
    """
    print()
    print(_SEP)
    print("  [SYNTH 3]  Halt path — briefing produced even on halted_kyc")
    print("             LLM forced to fail → templated briefing → halt headline")
    print("             Layer 2 must not alter any Layer 1 field")
    print(_SEP)

    with patch("agents.orchestrator.synthesis.call_agent_model") as mock_cam:
        mock_cam.side_effect = ModelUnavailableError(
            agent_name="orchestrator",
            primary="claude-opus-4-8",
            fallback="claude-sonnet-4-6",
            last_error="test-induced unavailability",
        )

        decision, events = run_pipeline(
            _MOCK_RECORD,
            _agent_overrides=_KYC_HALT_OVERRIDES,
        )

    briefing = decision.get("briefing")

    _check("Pipeline completed despite halt + LLM failure",
           True, got="returned normally")
    _check("decision_record['briefing'] present on halt path",
           briefing is not None, got=type(briefing).__name__)
    _check("briefing['source'] = 'templated_fallback'",
           briefing.get("source") == "templated_fallback",
           got=briefing.get("source"))

    # Headline must reflect the halt
    headline = briefing.get("headline", "")
    headline_upper = headline.upper()
    _check("headline reflects KYC halt (contains HALT, HALTED, or KYC)",
           any(w in headline_upper for w in ("HALT", "KYC")),
           got=headline[:80])

    # Recommendation must defer to human / mention escalation / compliance
    recommendation = briefing.get("recommendation", "").lower()
    _check("recommendation defers to human (contains escalat/compliance/legal/head/human/final)",
           any(w in recommendation for w in
               ("escalat", "compliance", "legal", "head", "human", "final decision")),
           got=briefing.get("recommendation", "")[:80])

    _check("per_agent_summary non-empty (agents that ran are listed)",
           len(briefing.get("per_agent_summary", [])) >= 1,
           got=f"{len(briefing.get('per_agent_summary', []))} entries")

    # briefing_complete event present
    bc_events = [e for e in events if e["event"] == "briefing_complete"]
    _check("'briefing_complete' event emitted on halt path",
           len(bc_events) == 1, got=f"{len(bc_events)} event(s)")

    # Layer 1 integrity — halt path fields
    _check_layer1_untouched(
        decision,
        expected_status="halted_kyc",
        expected_gate="halt",
        expected_seal_st="blocked",
        test_label="SYNTH 3",
    )

    # Confirm token_structure = None (tokenizer was skipped on halt)
    _check("token_structure = None (Layer 2 did not add a phantom token structure)",
           decision["token_structure"] is None,
           got=decision["token_structure"])

    print(f"\n    Halt headline: {headline[:80]}")
    print(f"    Recommendation excerpt: {briefing.get('recommendation', '')[:80]}...")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY · Orchestrator · Layer 2 Synthesis Test")
    print("  No real LLM calls. call_agent_model and synthesize_briefing are mocked.")
    print("  ConsensusSigner is REAL (ECDSA — always is).")
    print(_SEP2)

    test_synthesis_llm_success()
    test_synthesis_llm_failure_templated_fallback()
    test_synthesis_halt_path_templated()

    n_checks = len(_total)
    n_fail   = len(_failures)
    n_pass   = n_checks - n_fail

    print()
    print(_SEP2)
    if not _failures:
        print(f"  {_OK}  All 3 synthesis paths × {n_checks} assertions passed.")
        print(f"       Layer 2 confirmed: additive only, zero authority over Layer 1 decisions.")
    else:
        print(f"  {n_pass}/{n_checks} assertions passed. {n_fail} FAILED:")
        for f in _failures:
            print(f"    {_FAIL}  {f}")
    print(_SEP2)
    print()
    sys.exit(1 if _failures else 0)
