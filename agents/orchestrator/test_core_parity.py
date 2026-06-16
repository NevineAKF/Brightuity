"""
agents/orchestrator/test_core_parity.py
Brightuity — Parity test: core.py functions vs run_pipeline() end-to-end.

Verifies that calling evaluate_governance_gate / seal_decision / build_decision_record
directly from core.py produces byte-identical gate_outcome, seal.status, and
pipeline_status to what run_pipeline() returns for the same verdicts.

Three scenarios:
  1. all-pass  → gate_outcome="pass", seal.status="sealed",   pipeline="approved_pending_human"
  2. KYC halt  → gate_outcome="halt", seal.status="blocked",  pipeline="halted_kyc"
  3. gate block → gate_outcome="blocked", seal.status="blocked", pipeline="blocked_gate"

Run as: python agents/orchestrator/test_core_parity.py
"""
from __future__ import annotations

import sys
import os

# Allow running from repo root with: python agents/orchestrator/test_core_parity.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.orchestrator.core import (
    evaluate_governance_gate,
    seal_decision,
    build_decision_record,
)
from agents.orchestrator.orchestrator import run_pipeline

# ── Mock agent factories ────────────────────────────────────────────────────────

def _doc(verdict: str):
    def fn(r): return {"verdict": verdict, "summary": f"doc={verdict}", "issues_found": [], "model_used": "mock", "was_fallback": False, "latency_ms": 1}
    return fn

def _kyc(verdict: str):
    def fn(r): return {"verdict": verdict, "summary": f"kyc={verdict}", "flags_raised": [], "model_used": "mock", "was_fallback": False, "latency_ms": 1}
    return fn

def _comp(verdict: str):
    def fn(r): return {"verdict": verdict, "summary": f"comp={verdict}", "jurisdiction": "EU", "citations": [], "concerns": [], "retrieved_k": 0, "model_used": "mock", "was_fallback": False, "latency_ms": 1}
    return fn

def _stress(verdict: str):
    def fn(r): return {"verdict": verdict, "summary": f"stress={verdict}", "risk_level": "low", "risk_factors": [], "model_used": "mock", "was_fallback": False, "latency_ms": 1}
    return fn

def _token(verdict: str = "pass"):
    def fn(r): return {"verdict": verdict, "summary": "token=pass", "token_standard": "ERC-3643", "total_tokens": 1000, "value_per_token_eur": 1.0, "structure_notes": [], "model_used": "mock", "was_fallback": False, "latency_ms": 1}
    return fn

def _synth(r):
    return {"headline": "mock briefing", "decisive_factor": "test", "per_agent_summary": [], "recommendation": "n/a", "source": "mock", "model_used": "mock", "was_fallback": False, "latency_ms": 0}

_DUMMY_CLIENT = {
    "request_id": "REQ-PARITY",
    "client_id": "CLI-PARITY",
    "asset_type": "real_estate",
    "asset_value_eur": 100000.0,
    "submitted_at": "2026-01-01T00:00:00Z",
}

# ── Helper ──────────────────────────────────────────────────────────────────────

def _run_core(doc_v, kyc_v, comp_v, stress_v, include_token: bool):
    """Call core functions directly and return (gate_outcome, seal_status, pipeline_status)."""
    doc_r    = {"verdict": doc_v,    "summary": ""}
    kyc_r    = {"verdict": kyc_v,    "summary": ""}
    comp_r   = {"verdict": comp_v,   "summary": ""}
    stress_r = {"verdict": stress_v, "summary": ""}

    gate_outcome, gate_reason = evaluate_governance_gate(doc_r, kyc_r, comp_r, stress_r)

    agent_results: dict = {
        "doc_auditor":        doc_r,
        "kyc_guardian":       kyc_r,
        "dynamic_compliance": comp_r,
        "stress_test":        stress_r,
        "asset_tokenizer":    {"verdict": "pass", "summary": ""} if include_token else None,
    }

    case_record = {k: _DUMMY_CLIENT[k] for k in ("request_id", "client_id", "asset_type", "asset_value_eur", "submitted_at")}
    agent_verdicts = {k: v for k, v in agent_results.items() if v is not None}
    seal = seal_decision(case_record, agent_verdicts)

    if kyc_r.get("verdict") == "halt":
        pipeline_status = "halted_kyc"
    elif seal.get("status") == "sealed":
        pipeline_status = "approved_pending_human"
    else:
        pipeline_status = "blocked_gate"

    return gate_outcome, seal.get("status"), pipeline_status


def _run_pipeline(doc_v, kyc_v, comp_v, stress_v, include_token: bool):
    """Call run_pipeline with mocks and return (gate_outcome, seal_status, pipeline_status)."""
    overrides = {
        "doc_auditor":        _doc(doc_v),
        "kyc_guardian":       _kyc(kyc_v),
        "dynamic_compliance": _comp(comp_v),
        "stress_test":        _stress(stress_v),
    }
    if include_token:
        overrides["asset_tokenizer"] = _token()

    record, _ = run_pipeline(
        _DUMMY_CLIENT,
        _agent_overrides=overrides,
        _synthesis_override=_synth,
    )
    return (
        record["gate_outcome"],
        record["seal"]["status"] if record.get("seal") else None,
        record["pipeline_status"],
    )


# ── Scenarios ───────────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "all-pass",
        "doc_v": "pass", "kyc_v": "pass", "comp_v": "pass", "stress_v": "pass",
        "include_token": True,
        "expect_gate":     "pass",
        "expect_seal":     "sealed",
        "expect_pipeline": "approved_pending_human",
    },
    {
        "name": "kyc-halt",
        "doc_v": "pass", "kyc_v": "halt", "comp_v": "pass", "stress_v": "pass",
        "include_token": False,
        "expect_gate":     "halt",
        "expect_seal":     "blocked",
        "expect_pipeline": "halted_kyc",
    },
    {
        "name": "gate-block (doc fail)",
        "doc_v": "fail", "kyc_v": "pass", "comp_v": "pass", "stress_v": "pass",
        "include_token": False,
        "expect_gate":     "blocked",
        "expect_seal":     "blocked",
        "expect_pipeline": "blocked_gate",
    },
]

# ── Runner ───────────────────────────────────────────────────────────────────────

def main() -> None:
    passed = 0
    failed = 0

    for s in SCENARIOS:
        name    = s["name"]
        doc_v   = s["doc_v"];  kyc_v = s["kyc_v"]
        comp_v  = s["comp_v"]; stress_v = s["stress_v"]
        inc_tok = s["include_token"]
        exp_g   = s["expect_gate"]
        exp_s   = s["expect_seal"]
        exp_p   = s["expect_pipeline"]

        core_g, core_s, core_p = _run_core(doc_v, kyc_v, comp_v, stress_v, inc_tok)
        pipe_g, pipe_s, pipe_p = _run_pipeline(doc_v, kyc_v, comp_v, stress_v, inc_tok)

        ok = (
            core_g == exp_g and core_s == exp_s and core_p == exp_p
            and pipe_g == exp_g and pipe_s == exp_s and pipe_p == exp_p
            and core_g == pipe_g and core_s == pipe_s and core_p == pipe_p
        )

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
            print(f"[{status}] {name}")
        else:
            failed += 1
            print(f"[{status}] {name}")
            if core_g != exp_g or core_s != exp_s or core_p != exp_p:
                print(f"  core:     gate={core_g!r} seal={core_s!r} pipeline={core_p!r}")
                print(f"  expected: gate={exp_g!r} seal={exp_s!r} pipeline={exp_p!r}")
            if pipe_g != exp_g or pipe_s != exp_s or pipe_p != exp_p:
                print(f"  pipeline: gate={pipe_g!r} seal={pipe_s!r} pipeline={pipe_p!r}")
                print(f"  expected: gate={exp_g!r} seal={exp_s!r} pipeline={exp_p!r}")
            if core_g != pipe_g or core_s != pipe_s or core_p != pipe_p:
                print(f"  PARITY MISMATCH: core vs pipeline diverged")
                print(f"  core:     gate={core_g!r} seal={core_s!r} pipeline={core_p!r}")
                print(f"  pipeline: gate={pipe_g!r} seal={pipe_s!r} pipeline={pipe_p!r}")

    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(SCENARIOS)} scenarios")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
