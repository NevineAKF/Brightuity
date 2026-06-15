"""
agents/orchestrator/test_orchestrator_mocked.py
Brightuity — Orchestrator mocked control-flow test.

Proves ALL pipeline paths in milliseconds using injected mock agents.
No real LLM calls, no network I/O. Every assertion is deterministic.
Suitable for CI — this is the test the pipeline was built against.

Five paths covered:
  1. Happy path        — all 5 agents pass → seal succeeds → approved_pending_human
  2. KYC halt          — kyc="halt" → no tokenizer → seal blocked → halted_kyc
  3. Gate blocked      — compliance="fail" → no tokenizer → seal blocked → blocked_gate
  4. Agent exception   — stress_test raises → isolated → advisory pass → tokenizer runs
                          → seal blocked on stress_test → blocked_gate (no crash)
  5. Parallel stage-1  — 4 agents × 300ms → wall_ms ≈ 300ms (not 1200ms sequential)

Dual-layer gate system (verified by test 4):
  Layer 1 — Orchestrator: stress_test is advisory — a stress exception or fail
             does NOT block the orchestrator gate. The tokenizer still runs so
             the human reviewer sees the proposed structure alongside the risk
             assessment. Full picture, informed decision.
  Layer 2 — ConsensusSigner: requires ALL FIVE gates to return "pass" before
             issuing a seal. A stress_test fail → seal blocked → blocked_gate.
             This prevents a sealed proof from being produced for a high-risk asset
             while still surfacing the token structure for human review.

Run:
    python -m agents.orchestrator.test_orchestrator_mocked
  or:
    python agents/orchestrator/test_orchestrator_mocked.py
"""

from __future__ import annotations

import logging
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Suppress INFO logs during tests — only WARNING+ goes to stderr.
# Swap to DEBUG if you want to watch the full orchestrator event trace.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

from agents.orchestrator.orchestrator import run_pipeline

# ── Output symbols ─────────────────────────────────────────────────────────────
_OK   = "✓"
_FAIL = "✗"
_SEP  = "─" * 70
_SEP2 = "═" * 70


# ── Mock client record ─────────────────────────────────────────────────────────
# Mirrors a real client record. The ConsensusSigner picks:
#   request_id, client_id, asset_type, asset_value_eur, submitted_at.
# Other fields (full_name, etc.) are ignored by the signer — they stay in DB1.
_MOCK_RECORD: dict = {
    "request_id":     "REQ-TEST-001",
    "client_id":      "CLT-MOCK",
    "asset_type":     "Mock Property",
    "asset_value_eur": 1_000_000,
    "submitted_at":   "2026-06-15T00:00:00",
    "full_name":      "Test User",
    "nationality":    "Germany",
    "asset_detail":   "Mock asset for orchestrator control-flow test",
    "risk_flags":     [],
}


# ── Mock agent constructors ───────────────────────────────────────────────────

def _v(agent: str, verdict: str, **extra) -> dict:
    """Minimal mock verdict matching the real agent return schema."""
    return {
        "agent":        agent,
        "verdict":      verdict,
        "summary":      f"Mock {verdict} verdict for {agent}.",
        "model_used":   "mock",
        "was_fallback": False,
        "latency_ms":   1,
        **extra,
    }


# Doc Auditor
def _doc_pass(r):  return _v("doc_auditor", "pass", issues_found=[])
def _doc_fail(r):  return _v("doc_auditor", "fail", issues_found=["missing_deed"])

# KYC Guardian
def _kyc_pass(r):  return _v("kyc_guardian", "pass", flags_raised=[])
def _kyc_halt(r):  return _v("kyc_guardian", "halt",
                              summary="PEP match — hard halt.", flags_raised=["pep_match"])

# Dynamic Compliance
def _comp_pass(r): return _v("dynamic_compliance", "pass",
                              jurisdiction="EU", citations=[], concerns=[], retrieved_k=0)
def _comp_fail(r): return _v("dynamic_compliance", "fail",
                              jurisdiction="EU", citations=[],
                              concerns=["sanctioned_sector"], retrieved_k=0)

# Stress-Test Simulator
def _stress_pass(r):  return _v("stress_test", "pass",  risk_level="low",      risk_factors=[])
def _stress_raise(r): raise RuntimeError("Simulated infrastructure failure in stress-test agent")

# Asset Tokenizer
def _token_pass(r): return _v("asset_tokenizer", "pass",
                               token_standard="ERC-3643 T-REX",
                               total_tokens=1_000,
                               value_per_token_eur=1_000.0,
                               structure_notes=["Mock structure — QI only"])


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


# ── Test 1: Happy path ─────────────────────────────────────────────────────────

def test_happy_path() -> None:
    """
    All five mock agents return verdict='pass'.
    The real ConsensusSigner is used (no mock) — proves the end-to-end seal
    path works for a fully compliant case.
    """
    print()
    print(_SEP)
    print("  [TEST 1]  Happy path — all agents pass")
    print("            Real ConsensusSigner used — proves ECDSA seal on clean run.")
    print(_SEP)

    overrides = {
        "doc_auditor":        _doc_pass,
        "kyc_guardian":       _kyc_pass,
        "dynamic_compliance": _comp_pass,
        "stress_test":        _stress_pass,
        "asset_tokenizer":    _token_pass,
        # consensus_signer: not overridden → real ConsensusSigner.seal()
    }

    decision, events = run_pipeline(_MOCK_RECORD, _agent_overrides=overrides)

    status = decision["pipeline_status"]
    gate   = decision["gate_outcome"]
    seal   = decision["seal"] or {}
    token  = decision["token_structure"]

    _check("pipeline_status = approved_pending_human",
           status == "approved_pending_human", got=status)
    _check("gate_outcome = pass",
           gate == "pass", got=gate)
    _check("token_structure present (tokenizer ran)",
           token is not None and token.get("verdict") == "pass",
           got=token.get("verdict") if token else None)
    _check("seal.status = sealed  (real ECDSA seal produced)",
           seal.get("status") == "sealed", got=seal.get("status"))
    _check("seal.canonical_hash starts with 'sha256:'",
           str(seal.get("canonical_hash", "")).startswith("sha256:"),
           got=str(seal.get("canonical_hash", ""))[:16] + "...")
    _check("seal.signature present (non-empty DER hex)",
           len(seal.get("signature", "")) > 32,
           got=seal.get("signature", "")[:16] + "...")
    _check("seal.gates_cleared = 5",
           len(seal.get("gates_cleared", [])) == 5,
           got=len(seal.get("gates_cleared", [])))
    _check("event log non-empty",
           len(events) > 0, got=f"{len(events)} events")
    _check("pipeline_complete event present in log",
           any(e["event"] == "pipeline_complete" for e in events), got="found")

    print(f"\n    stage1_wall_ms = {decision['stage1_wall_ms']}ms  "
          f"| total_wall_ms = {decision['total_wall_ms']}ms")


# ── Test 2: KYC halt ───────────────────────────────────────────────────────────

def test_kyc_halt() -> None:
    """
    KYC Guardian returns 'halt' — the most severe verdict.
    Expected: hard stop, no tokenizer, seal blocked on kyc_guardian, halted_kyc.
    """
    print()
    print(_SEP)
    print("  [TEST 2]  KYC halt — pipeline hard stop")
    print("            Expects: gate=halt → tokenizer skipped → seal blocked → halted_kyc")
    print(_SEP)

    overrides = {
        "doc_auditor":        _doc_pass,
        "kyc_guardian":       _kyc_halt,      # ← HALT
        "dynamic_compliance": _comp_pass,
        "stress_test":        _stress_pass,
        "asset_tokenizer":    _token_pass,    # must NOT be called
    }

    decision, events = run_pipeline(_MOCK_RECORD, _agent_overrides=overrides)

    status = decision["pipeline_status"]
    gate   = decision["gate_outcome"]
    seal   = decision["seal"] or {}
    token  = decision["token_structure"]

    _check("pipeline_status = halted_kyc",
           status == "halted_kyc", got=status)
    _check("gate_outcome = halt",
           gate == "halt", got=gate)
    _check("token_structure = None  (tokenizer skipped on hard stop)",
           token is None, got=token)
    _check("seal.status = blocked",
           seal.get("status") == "blocked", got=seal.get("status"))
    _check("seal.failed_gate = kyc_guardian",
           seal.get("failed_gate") == "kyc_guardian", got=seal.get("failed_gate"))
    _check("seal.sealed_at = None  (no signature produced)",
           seal.get("sealed_at") is None, got=seal.get("sealed_at"))

    stage2_skips = [e for e in events if e["event"] == "stage2_skip"]
    _check("stage2_skip event emitted with gate_outcome=halt",
           len(stage2_skips) == 1 and stage2_skips[0].get("gate_outcome") == "halt",
           got=stage2_skips[0].get("gate_outcome") if stage2_skips else "missing")

    print(f"\n    KYC verdict: '{decision['agents']['kyc_guardian']['verdict']}' "
          f"| flags: {decision['agents']['kyc_guardian'].get('flags_raised')}")


# ── Test 3: Mandatory gate blocked ────────────────────────────────────────────

def test_gate_blocked() -> None:
    """
    Dynamic Compliance returns 'fail' — a mandatory hard gate.
    Expected: tokenizer skipped, seal blocked on dynamic_compliance, blocked_gate.
    """
    print()
    print(_SEP)
    print("  [TEST 3]  Mandatory gate blocked — compliance fail")
    print("            Expects: gate=blocked → tokenizer skipped → seal blocked → blocked_gate")
    print(_SEP)

    overrides = {
        "doc_auditor":        _doc_pass,
        "kyc_guardian":       _kyc_pass,
        "dynamic_compliance": _comp_fail,     # ← FAIL (mandatory gate)
        "stress_test":        _stress_pass,
        "asset_tokenizer":    _token_pass,    # must NOT be called
    }

    decision, events = run_pipeline(_MOCK_RECORD, _agent_overrides=overrides)

    status = decision["pipeline_status"]
    gate   = decision["gate_outcome"]
    seal   = decision["seal"] or {}
    token  = decision["token_structure"]

    _check("pipeline_status = blocked_gate",
           status == "blocked_gate", got=status)
    _check("gate_outcome = blocked",
           gate == "blocked", got=gate)
    _check("gate_reason mentions dynamic_compliance",
           "dynamic_compliance" in decision.get("gate_reason", ""),
           got=decision.get("gate_reason", "")[:60] + "...")
    _check("token_structure = None  (tokenizer skipped)",
           token is None, got=token)
    _check("seal.status = blocked",
           seal.get("status") == "blocked", got=seal.get("status"))
    _check("seal.failed_gate = dynamic_compliance",
           seal.get("failed_gate") == "dynamic_compliance", got=seal.get("failed_gate"))

    stage2_skips = [e for e in events if e["event"] == "stage2_skip"]
    _check("stage2_skip event emitted",
           len(stage2_skips) == 1, got=f"{len(stage2_skips)} event(s)")

    print(f"\n    compliance concerns: "
          f"{decision['agents']['dynamic_compliance'].get('concerns')}")


# ── Test 4: Agent exception isolation ─────────────────────────────────────────

def test_agent_exception_isolation() -> None:
    """
    stress_test agent raises an uncaught RuntimeError.

    Verifies isolation (other agents unaffected), safe default application,
    and the dual-layer gate behaviour:

      Layer 1 (orchestrator): stress_test is ADVISORY.
        The exception is caught. Safe default: verdict='fail', 'exception' key
        present. The mandatory gates (doc+kyc+compliance) all passed, so
        gate_outcome = 'pass'. Tokenizer RUNS — the human sees the proposed
        structure alongside the risk assessment.

      Layer 2 (ConsensusSigner): ALL 5 gates must be 'pass' to seal.
        stress_test verdict='fail' → seal blocked on 'stress_test'.
        pipeline_status = 'blocked_gate'.

    Net result: the human reviewer gets both the tokenizer proposal AND the
    risk exception visible in the decision record. Informed decision, no blind
    block, no crash, no seal without full gate clearance.
    """
    print()
    print(_SEP)
    print("  [TEST 4]  Agent exception isolation — stress_test raises")
    print("            Expects: isolated → advisory gate=pass → tokenizer runs")
    print("                     → ConsensusSigner blocks on stress → blocked_gate")
    print(_SEP)

    overrides = {
        "doc_auditor":        _doc_pass,
        "kyc_guardian":       _kyc_pass,
        "dynamic_compliance": _comp_pass,
        "stress_test":        _stress_raise,  # ← RAISES RuntimeError
        "asset_tokenizer":    _token_pass,
    }

    decision, events = run_pipeline(_MOCK_RECORD, _agent_overrides=overrides)

    status        = decision["pipeline_status"]
    gate          = decision["gate_outcome"]
    seal          = decision["seal"] or {}
    token         = decision["token_structure"]
    stress_result = decision["agents"].get("stress_test", {})

    _check("No crash — pipeline completed despite agent exception",
           True, got="returned normally")
    _check("pipeline_status = blocked_gate",
           status == "blocked_gate", got=status)
    _check("gate_outcome = pass  (stress is advisory at orchestrator layer)",
           gate == "pass", got=gate)
    _check("stress_result has 'exception' key  (safe default applied, not swallowed)",
           "exception" in stress_result,
           got=stress_result.get("exception", "missing key")[:50])
    _check("stress verdict = fail  (conservative safe default)",
           stress_result.get("verdict") == "fail",
           got=stress_result.get("verdict"))
    _check("token_structure present  (tokenizer ran because gate=pass)",
           token is not None and token.get("verdict") == "pass",
           got=token.get("verdict") if token else None)
    _check("seal.status = blocked  (ConsensusSigner enforces stress gate)",
           seal.get("status") == "blocked", got=seal.get("status"))
    _check("seal.failed_gate = stress_test",
           seal.get("failed_gate") == "stress_test", got=seal.get("failed_gate"))
    _check("doc_auditor ran and passed  (thread isolation confirmed)",
           decision["agents"].get("doc_auditor", {}).get("verdict") == "pass",
           got=decision["agents"].get("doc_auditor", {}).get("verdict"))
    _check("kyc_guardian ran and passed  (thread isolation confirmed)",
           decision["agents"].get("kyc_guardian", {}).get("verdict") == "pass",
           got=decision["agents"].get("kyc_guardian", {}).get("verdict"))
    _check("dynamic_compliance ran and passed  (thread isolation confirmed)",
           decision["agents"].get("dynamic_compliance", {}).get("verdict") == "pass",
           got=decision["agents"].get("dynamic_compliance", {}).get("verdict"))

    print(f"\n    stress exception: {stress_result.get('exception', '—')}")
    print(f"    Dual-layer gate: orchestrator=pass (advisory), "
          f"ConsensusSigner=blocked (failed_gate=stress_test)")


# ── Test 5: Parallel stage-1 execution ────────────────────────────────────────

def test_parallel_stage1() -> None:
    """
    Each of the four stage-1 agents sleeps 300ms.
    Sequential execution would take ≥ 1200ms.
    ThreadPoolExecutor parallelism should yield ~300ms.
    Threshold: stage1_wall_ms < 700ms (allows 2× overhead for thread startup).
    """
    print()
    print(_SEP)
    print("  [TEST 5]  Parallel stage-1 execution  (concurrency proof)")
    print("            4 agents × 300ms → expect wall_ms ≈ 300ms (not 1200ms sequential)")
    print(_SEP)

    _SLEEP_S = 0.3

    def _slow(fn):
        def _inner(r):
            time.sleep(_SLEEP_S)
            return fn(r)
        return _inner

    overrides = {
        "doc_auditor":        _slow(_doc_pass),
        "kyc_guardian":       _slow(_kyc_pass),
        "dynamic_compliance": _slow(_comp_pass),
        "stress_test":        _slow(_stress_pass),
        "asset_tokenizer":    _token_pass,           # fast (stage 2, sequential)
    }

    decision, _ = run_pipeline(_MOCK_RECORD, _agent_overrides=overrides)

    stage1_ms    = decision["stage1_wall_ms"]
    sequential   = int(_SLEEP_S * 1000 * 4)   # 1200ms
    threshold    = int(_SLEEP_S * 1000 * 2)   # 600ms (generous)

    print(f"\n    stage1_wall_ms     = {stage1_ms}ms")
    print(f"    sequential would be ≥ {sequential}ms")
    print(f"    parallelism threshold < {threshold}ms")

    _check(f"stage1_wall_ms < {threshold}ms  (parallel, not sequential)",
           stage1_ms < threshold, got=f"{stage1_ms}ms")
    _check("pipeline_status = approved_pending_human  (all mock agents passed)",
           decision["pipeline_status"] == "approved_pending_human",
           got=decision["pipeline_status"])
    _check("All 4 stage-1 agents reported results",
           all(decision["agents"].get(a) is not None
               for a in ("doc_auditor", "kyc_guardian",
                         "dynamic_compliance", "stress_test")),
           got="all 4 present")

    if stage1_ms > 0:
        speedup = sequential / stage1_ms
        print(f"\n    Effective speedup: {speedup:.1f}×  (vs sequential {sequential}ms)")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY · Orchestrator · Mocked Control-Flow Test")
    print("  No LLM calls — all five agent functions are injected mocks.")
    print("  ConsensusSigner is REAL (ECDSA SECP256K1 — no LLM, no network).")
    print(_SEP2)

    test_happy_path()
    test_kyc_halt()
    test_gate_blocked()
    test_agent_exception_isolation()
    test_parallel_stage1()

    n_checks = len(_total)
    n_fail   = len(_failures)
    n_pass   = n_checks - n_fail

    print()
    print(_SEP2)
    if not _failures:
        print(f"  {_OK}  All 5 paths × {n_checks} assertions passed.")
    else:
        print(f"  {n_pass}/{n_checks} assertions passed. "
              f"{n_fail} FAILED:")
        for f in _failures:
            print(f"    {_FAIL}  {f}")
    print(_SEP2)
    print()
    sys.exit(1 if _failures else 0)
