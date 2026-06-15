"""
agents/orchestrator/test_orchestrator_http.py
Brightuity — Orchestrator HTTP transport path test.

Proves the AGENT_TRANSPORT=http path without starting real services.
httpx.post is patched in both tests — no network I/O, no LLM calls.
Synthesis is mocked via _synthesis_override. ConsensusSigner is REAL.

Two paths:
  1. HTTP success   — mocked httpx returns pass verdicts for all 5 agents.
                      Orchestrator routes through HTTP callables, ConsensusSigner
                      seals, pipeline_status = approved_pending_human.
  2. HTTP failure   — mocked httpx raises httpx.ConnectError for every call.
                      _safe_call catches each exception, applies safe defaults.
                      KYC safe default = "halt" → halted_kyc.
                      Proves: HTTP failures are handled exactly like in-process
                      exceptions — conservative default, no crash, no silent pass.

The existing 37/37 (mocked) and 39/39 (synthesis) tests are NOT called here.
Run those separately to confirm the inprocess path is untouched.

Run:
    python -m agents.orchestrator.test_orchestrator_http
  or:
    python agents/orchestrator/test_orchestrator_http.py
"""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock, patch

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

import httpx

from agents.orchestrator.orchestrator import run_pipeline

# ── Symbols ────────────────────────────────────────────────────────────────────
_OK   = "OK"
_FAIL = "FAIL"
_SEP  = "-" * 70
_SEP2 = "=" * 70

# ── Shared mock record ─────────────────────────────────────────────────────────
_MOCK_RECORD: dict = {
    "request_id":      "REQ-HTTP-TEST",
    "client_id":       "CLT-HTTP",
    "asset_type":      "Mock Property",
    "asset_value_eur": 1_000_000,
    "submitted_at":    "2026-06-15T00:00:00",
    "full_name":       "HTTP Test User",
    "nationality":     "Germany",
    "asset_detail":    "Mock asset for HTTP transport test",
    "risk_flags":      [],
}

# ── Mock synthesis (skips real LLM for both tests) ────────────────────────────
_MOCK_SYNTHESIS = lambda dr: {
    "headline":          "HTTP transport test — mock briefing",
    "decisive_factor":   "HTTP transport test",
    "per_agent_summary": [],
    "recommendation":    "Mock recommendation.",
    "source":            "mock",
    "model_used":        "none",
    "was_fallback":      False,
    "latency_ms":        0,
}

# ── httpx mock helpers ─────────────────────────────────────────────────────────
# URLs are the AGENT_HTTP_URLS defaults:  localhost:8001–8005
# The mock dispatches by port number — same as what _http_call will call.

def _mock_post_all_pass(url: str, **kwargs):
    """Return a structurally correct pass verdict for the agent at the given URL."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    if ":8001" in url:   # doc_auditor
        data = {
            "agent": "doc_auditor", "verdict": "pass",
            "summary": "HTTP mock — docs clean.", "issues_found": [],
            "model_used": "mock", "was_fallback": False, "latency_ms": 1,
        }
    elif ":8002" in url:  # kyc_guardian
        data = {
            "agent": "kyc_guardian", "verdict": "pass",
            "summary": "HTTP mock — KYC clear.", "flags_raised": [],
            "model_used": "mock", "was_fallback": False, "latency_ms": 1,
        }
    elif ":8003" in url:  # dynamic_compliance
        data = {
            "agent": "dynamic_compliance", "verdict": "pass",
            "summary": "HTTP mock — compliant.", "jurisdiction": "EU",
            "citations": [], "concerns": [], "retrieved_k": 0,
            "model_used": "mock", "was_fallback": False, "latency_ms": 1,
        }
    elif ":8004" in url:  # stress_test
        data = {
            "agent": "stress_test", "verdict": "pass",
            "summary": "HTTP mock — low risk.", "risk_level": "low",
            "risk_factors": [],
            "model_used": "mock", "was_fallback": False, "latency_ms": 1,
        }
    elif ":8005" in url:  # asset_tokenizer
        data = {
            "agent": "asset_tokenizer", "verdict": "pass",
            "summary": "HTTP mock — structure ready.",
            "token_standard": "ERC-3643 T-REX",
            "total_tokens": 1_000, "value_per_token_eur": 1_000.0,
            "structure_notes": ["HTTP mock note"],
            "model_used": "mock", "was_fallback": False, "latency_ms": 1,
        }
    else:
        raise ValueError(f"Unexpected URL in _mock_post_all_pass: {url!r}")

    mock_resp.json.return_value = data
    return mock_resp


def _mock_post_all_fail(url: str, **kwargs):
    """Simulate a network failure for every agent endpoint."""
    raise httpx.ConnectError(f"Connection refused (test): {url}")


# ── Assertion tracker ──────────────────────────────────────────────────────────
_failures: list[str] = []
_total:    list[None] = []


def _check(label: str, condition: bool, got=None) -> None:
    _total.append(None)
    suffix = f"  [{got}]" if got is not None else ""
    if condition:
        print(f"    [{_OK}]  {label}{suffix}")
    else:
        detail = f"  (got: {got!r})" if got is not None else ""
        print(f"    [{_FAIL}]  {label}{detail}")
        _failures.append(label)


# ── Test 1: HTTP success path ──────────────────────────────────────────────────

def test_http_success() -> None:
    """
    AGENT_TRANSPORT=http, httpx.post mocked to return pass verdicts for all agents.

    Proves:
    - The orchestrator routes Stage 1 and Stage 2 calls through _http_call.
    - Verdict dicts returned over HTTP flow through gates and ConsensusSigner
      identically to in-process calls.
    - pipeline_status = approved_pending_human, seal produced.
    - _agent_overrides is NOT set — pure HTTP transport path.
    """
    print()
    print(_SEP)
    print("  [TEST 1]  HTTP transport success path")
    print("            AGENT_TRANSPORT=http | httpx.post mocked | all agents pass")
    print(_SEP)

    with patch.dict(os.environ, {"AGENT_TRANSPORT": "http"}), \
         patch("agents.orchestrator.orchestrator.httpx.post",
               side_effect=_mock_post_all_pass):

        decision, events = run_pipeline(
            _MOCK_RECORD,
            _synthesis_override=_MOCK_SYNTHESIS,
        )

    status = decision["pipeline_status"]
    gate   = decision["gate_outcome"]
    seal   = decision["seal"] or {}
    token  = decision["token_structure"]

    _check("pipeline_status = approved_pending_human",
           status == "approved_pending_human", got=status)
    _check("gate_outcome = pass",
           gate == "pass", got=gate)
    _check("token_structure present (tokenizer ran via HTTP)",
           token is not None and token.get("verdict") == "pass",
           got=token.get("verdict") if token else None)
    _check("seal.status = sealed (real ECDSA seal on HTTP-sourced verdicts)",
           seal.get("status") == "sealed", got=seal.get("status"))
    _check("seal.canonical_hash present",
           str(seal.get("canonical_hash", "")).startswith("sha256:"),
           got=str(seal.get("canonical_hash", ""))[:20] + "...")
    _check("briefing present (synthesis ran)",
           "briefing" in decision and isinstance(decision["briefing"], dict),
           got=decision.get("briefing", {}).get("source"))
    _check("all 4 stage1 agents returned verdicts",
           all(decision["agents"].get(a, {}).get("verdict") == "pass"
               for a in ("doc_auditor", "kyc_guardian",
                         "dynamic_compliance", "stress_test")),
           got="all pass")
    _check("briefing_complete event in log",
           any(e["event"] == "briefing_complete" for e in events),
           got="found")

    print(f"\n    stage1_wall_ms = {decision['stage1_wall_ms']}ms"
          f"  |  total_wall_ms = {decision['total_wall_ms']}ms")


# ── Test 2: HTTP failure → safe default ───────────────────────────────────────

def test_http_failure_safe_default() -> None:
    """
    AGENT_TRANSPORT=http, httpx.post raises ConnectError for every call.

    Proves:
    - _safe_call catches the httpx exception identically to in-process exceptions.
    - KYC Guardian safe default = "halt" (never silently pass KYC on infra failure).
    - All other safe defaults = "fail".
    - Gate: kyc="halt" → gate_outcome="halt" → tokenizer skipped.
    - pipeline_status = halted_kyc (same outcome as in-process KYC exception).
    - The pipeline does NOT crash.
    """
    print()
    print(_SEP)
    print("  [TEST 2]  HTTP transport failure -> safe default")
    print("            AGENT_TRANSPORT=http | httpx.post raises ConnectError")
    print("            Expects: KYC safe default=halt -> halted_kyc (no crash)")
    print(_SEP)

    with patch.dict(os.environ, {"AGENT_TRANSPORT": "http"}), \
         patch("agents.orchestrator.orchestrator.httpx.post",
               side_effect=_mock_post_all_fail):

        decision, events = run_pipeline(
            _MOCK_RECORD,
            _synthesis_override=_MOCK_SYNTHESIS,
        )

    status = decision["pipeline_status"]
    gate   = decision["gate_outcome"]
    seal   = decision["seal"] or {}
    token  = decision["token_structure"]

    kyc_result   = decision["agents"].get("kyc_guardian",       {})
    doc_result   = decision["agents"].get("doc_auditor",         {})
    stress_result = decision["agents"].get("stress_test",        {})

    _check("No crash — pipeline completed despite all HTTP failures",
           True, got="returned normally")
    _check("pipeline_status = halted_kyc (KYC infra failure -> conservative halt)",
           status == "halted_kyc", got=status)
    _check("gate_outcome = halt",
           gate == "halt", got=gate)
    _check("token_structure = None (tokenizer skipped on halt)",
           token is None, got=token)
    _check("seal.status = blocked",
           seal.get("status") == "blocked", got=seal.get("status"))
    # ConsensusSigner checks MANDATORY_GATES in order: doc_auditor first.
    # With all agents failing via HTTP, doc_auditor (verdict="fail") is the
    # first gate the signer encounters — so failed_gate="doc_auditor".
    # The orchestrator correctly sets pipeline_status=halted_kyc from the gate
    # logic; the signer's failed_gate reflects its own ordered check.
    _check("seal.failed_gate is first failed mandatory gate (doc_auditor)",
           seal.get("failed_gate") == "doc_auditor", got=seal.get("failed_gate"))
    _check("kyc_guardian verdict = halt (conservative safe default)",
           kyc_result.get("verdict") == "halt", got=kyc_result.get("verdict"))
    _check("kyc_guardian result has 'exception' key (safe default, not swallowed)",
           "exception" in kyc_result,
           got=kyc_result.get("exception", "missing")[:60] if "exception" in kyc_result else "missing")
    _check("doc_auditor result has 'exception' key (safe default applied)",
           "exception" in doc_result,
           got="present")
    _check("stage2_skip event emitted",
           any(e["event"] == "stage2_skip" for e in events), got="found")
    _check("briefing present even on halted pipeline",
           "briefing" in decision and isinstance(decision["briefing"], dict),
           got=decision.get("briefing", {}).get("source"))

    print(f"\n    kyc exception: {kyc_result.get('exception', '(none)')[:80]}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY - Orchestrator HTTP Transport Path Test")
    print("  No real services started. httpx.post mocked for both tests.")
    print("  ConsensusSigner is REAL (ECDSA SECP256K1). Synthesis is mocked.")
    print(_SEP2)

    test_http_success()
    test_http_failure_safe_default()

    n_checks = len(_total)
    n_fail   = len(_failures)
    n_pass   = n_checks - n_fail

    print()
    print(_SEP2)
    if not _failures:
        print(f"  [{_OK}]  All 2 paths x {n_checks} assertions passed.")
    else:
        print(f"  {n_pass}/{n_checks} assertions passed. {n_fail} FAILED:")
        for f in _failures:
            print(f"    [{_FAIL}]  {f}")
    print(_SEP2)
    print()
    sys.exit(1 if _failures else 0)
