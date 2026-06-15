"""
backend/test_backend_authorization.py
Brightuity — Human authorization + e-signature test suite.

Tests the Layer 2 integrity model end-to-end via FastAPI TestClient.
No real LLM calls: agents mocked. ConsensusSigner REAL (Layer 1 ECDSA).
Authorization signer REAL (Layer 2 ECDSA, persistent demo keypair).

Test paths:
  PATH A — APPROVE:          run REQ-2041 (all-pass) → POST /authorize {approve}
             Asserts: status=authorized, auth block signed, signatory present,
             final_decision=approved, signature+hash non-empty.
  PATH B — VERIFY passes:    GET /verify → verified=True on the signed package.
  PATH C — TAMPER detection: mutate a risk_score in the stored package →
             verify_authorization() returns False → "TAMPER DETECTED" proof.
  PATH D — REJECT:           run REQ-2042 (all-pass) → POST /authorize {reject}
             Asserts: status=rejected, decision=rejected, still signed.
  PATH E — HALTED can't authorize: REQ-2043 (KYC halt) → POST /authorize → 409.
  PATH F — DOUBLE-SIGN blocked: second authorize on REQ-2041 → 409.
  PATH G — PERSISTENCE:      fresh case_store reads confirm decision columns +
             patched human_authorization in SQLite (not just memory).

Run:
    python -m backend.test_backend_authorization
  or:
    python backend/test_backend_authorization.py
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import tempfile

# ── Set test paths BEFORE any backend imports ──────────────────────────────────
# Both get_db_path() and _key_path() read os.environ at call time, so setting
# these before the lifespan fires is sufficient. Never touches production files.
_TMP_DB  = tempfile.NamedTemporaryFile(suffix=".db",  delete=False)
_TMP_KEY = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
_TMP_DB.close()
_TMP_KEY.close()
os.environ["CASES_DB_PATH"] = _TMP_DB.name
os.environ["AUTH_KEY_PATH"] = _TMP_KEY.name

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# ── UTF-8 output ───────────────────────────────────────────────────────────────
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── Backend imports (after env vars are set) ───────────────────────────────────
from starlette.testclient import TestClient

from backend.main import app, _pipeline_agent_overrides, _pipeline_synthesis_override
from backend import case_state, case_store, authorization_signer

# Reset any cached keypair from a prior test run in this process
authorization_signer.reset_keypair_for_testing()

# ── Symbols ────────────────────────────────────────────────────────────────────
_OK   = "OK"
_FAIL = "FAIL"
_SEP  = "-" * 72
_SEP2 = "=" * 72

_failures: list[str] = []
_checks:   list[None] = []


def _check(label: str, condition: bool, got: object = None) -> None:
    _checks.append(None)
    suffix = f"  [got: {got!r}]" if got is not None else ""
    mark   = _OK if condition else _FAIL
    print(f"    [{mark}]  {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── Mock agents (same pattern as test_governance_audit and test_backend_pipeline) ──

def _mock_doc_pass(cr: dict) -> dict:
    return {"agent": "doc_auditor", "verdict": "pass",
            "summary": "All documents verified.", "issues_found": [],
            "model_used": "mock", "was_fallback": False, "latency_ms": 100}

def _mock_kyc_pass(cr: dict) -> dict:
    return {"agent": "kyc_guardian", "verdict": "pass",
            "summary": "Identity verified. No watchlist hit.",
            "flags_raised": [], "model_used": "mock", "was_fallback": False,
            "latency_ms": 120,
            "screening_result": {"matched": False, "match_type": None,
                                 "matched_entry": None, "match_score": 0.0,
                                 "sources_checked": ["EU Consolidated Sanctions List",
                                                     "FATF PEP Register"]}}

def _mock_kyc_halt(cr: dict) -> dict:
    return {"agent": "kyc_guardian", "verdict": "halt",
            "summary": "WL-001 PEP match. Hard stop.",
            "flags_raised": ["WL-001 PEP match"],
            "model_used": "mock", "was_fallback": False, "latency_ms": 130,
            "screening_result": {"matched": True, "match_type": "pep",
                                 "matched_entry": {"id": "WL-001", "name": "Viktor Petrov",
                                                   "type": "pep", "country": "Cyprus",
                                                   "source": "FATF PEP Register",
                                                   "listed_since": "2023-11-14", "notes": ""},
                                 "match_score": 1.0,
                                 "sources_checked": ["FATF PEP Register"]}}

def _mock_compliance_pass(cr: dict) -> dict:
    return {"agent": "dynamic_compliance", "verdict": "pass",
            "summary": "MiCA compliant.", "jurisdiction": "Germany (EU)",
            "citations": ["MiCA Art. 17"], "concerns": [], "retrieved_k": 2,
            "model_used": "mock", "was_fallback": False, "latency_ms": 140}

def _mock_stress_pass(cr: dict) -> dict:
    return {"agent": "stress_test", "verdict": "pass",
            "summary": "Risk score 38/100 (medium).", "risk_level": "medium",
            "risk_factors": ["Commercial property illiquidity 10%"],
            "model_used": "mock", "was_fallback": False, "latency_ms": 110,
            "risk_metrics": {
                "base_valuation": 2_000_000.0, "asset_type": "Commercial Property",
                "illiquidity_discount": 0.10, "market_volatility": 0.12,
                "market_stress_scenarios": {"market_downturn_20pct_eur": 1_600_000,
                                            "liquidity_crisis_eur": 1_440_000,
                                            "interest_rate_shock_eur": 1_640_000},
                "stressed_value_range": {"worst_case_eur": 1_440_000,
                                         "base_case_eur": 2_000_000,
                                         "best_case_eur": 2_200_000},
                "score_components": {"illiquidity_score": 13, "volatility_score": 17,
                                     "concentration_score": 8, "flags_score": 0},
                "risk_score": 38, "risk_level": "medium", "verdict": "pass",
                "risk_factors": ["Commercial property illiq. (10%)"],
                "methodology": "38/100"}}

def _mock_tokenizer_pass(cr: dict) -> dict:
    return {"agent": "asset_tokenizer", "verdict": "pass",
            "summary": "ERC-3643 T-REX. 2,000 tokens @ EUR 1,000.",
            "token_standard": "ERC-3643 T-REX", "total_tokens": 2_000,
            "value_per_token_eur": 1_000.0,
            "structure_notes": ["EU qualified investors only"],
            "model_used": "mock", "was_fallback": False, "latency_ms": 90}

def _mock_synthesis(dr: dict) -> dict:
    status = dr.get("pipeline_status", "unknown")
    return {"headline": f"Mock — {status}", "decisive_factor": "Mock.",
            "per_agent_summary": ["Mock summary."], "recommendation": "Human review.",
            "source": "mock", "model_used": "none", "was_fallback": False, "latency_ms": 0}

_ALL_PASS  = {"doc_auditor": _mock_doc_pass, "kyc_guardian": _mock_kyc_pass,
              "dynamic_compliance": _mock_compliance_pass, "stress_test": _mock_stress_pass,
              "asset_tokenizer": _mock_tokenizer_pass}
_KYC_HALT  = {**_ALL_PASS, "kyc_guardian": _mock_kyc_halt}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _set_overrides(agent_overrides: dict | None, synthesis=None) -> None:
    app.dependency_overrides[_pipeline_agent_overrides] = lambda: agent_overrides
    app.dependency_overrides[_pipeline_synthesis_override] = lambda: (synthesis or _mock_synthesis)


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def _run_to_awaiting(client: TestClient, request_id: str) -> None:
    """Helper: run the pipeline and assert it reaches awaiting_decision."""
    resp = client.post(f"/cases/{request_id}/run")
    assert resp.status_code == 202, f"POST /run failed: {resp.text}"
    status = client.get(f"/cases/{request_id}/status").json()
    assert status["status"] == "awaiting_decision", (
        f"Expected awaiting_decision, got {status['status']}"
    )


# ── PATH A — Approve ───────────────────────────────────────────────────────────

def test_approve(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH A — APPROVE (REQ-2041, Marcus Weber)")
    print("           Layer 2 ECDSA signed. Layer 1 ECDSA real. Agents mocked.")
    print(_SEP)

    _set_overrides(_ALL_PASS)
    try:
        _run_to_awaiting(client, "REQ-2041")

        resp = client.post("/cases/REQ-2041/authorize", json={
            "decision":       "approve",
            "rationale":      "All five compliance gates cleared. Risk within tolerance. "
                              "Tokenization structure appropriate for EU qualified investors.",
            "signatory_name": "Nevine AKF",
            "signatory_role": "Head of Digital Assets",
            "annotations":    ["Reviewed ERC-3643 structure", "Verified FATF no-hit"],
        })
        _check("POST /authorize returns 200", resp.status_code == 200,
               got=resp.status_code)
        body = resp.json()
        _check("response.status = authorized", body.get("status") == "authorized",
               got=body.get("status"))

        auth = body.get("human_authorization", {})
        _check("human_authorization.decision = approved",
               auth.get("decision") == "approved", got=auth.get("decision"))
        _check("human_authorization.signatory_name = Nevine AKF",
               auth.get("signatory_name") == "Nevine AKF",
               got=auth.get("signatory_name"))
        _check("human_authorization.signatory_role = Head of Digital Assets",
               auth.get("signatory_role") == "Head of Digital Assets",
               got=auth.get("signatory_role"))
        _check("human_authorization.signed_at is non-empty",
               bool(auth.get("signed_at")), got=auth.get("signed_at"))
        _check("human_authorization.authorization_hash starts with sha256:",
               (auth.get("authorization_hash") or "").startswith("sha256:"),
               got=(auth.get("authorization_hash") or "")[:24])
        _check("human_authorization.authorization_signature is non-empty hex",
               len(auth.get("authorization_signature") or "") > 32,
               got=len(auth.get("authorization_signature") or ""))
        _check("human_authorization.public_key is non-empty hex",
               len(auth.get("public_key") or "") == 66,   # 33 bytes compressed = 66 hex chars
               got=len(auth.get("public_key") or ""))
        _check("human_authorization.curve = SECP256K1",
               auth.get("curve") == "SECP256K1", got=auth.get("curve"))
        _check("human_authorization.annotations has 2 entries",
               len(auth.get("annotations", [])) == 2,
               got=len(auth.get("annotations", [])))

        # Case status via GET /status
        s = client.get("/cases/REQ-2041/status").json()
        _check("GET /status shows status = authorized",
               s.get("status") == "authorized", got=s.get("status"))

        # Package has final_decision set
        pkg = client.get("/cases/REQ-2041/package").json()
        _check("package.case_summary.final_decision = approved",
               pkg["case_summary"]["final_decision"] == "approved",
               got=pkg["case_summary"]["final_decision"])
        _check("package.human_authorization is non-null",
               pkg.get("human_authorization") is not None)

    finally:
        _clear_overrides()


# ── PATH B — Verify passes ────────────────────────────────────────────────────

def test_verify_passes(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH B — VERIFY passes (GET /verify on freshly signed package)")
    print(_SEP)

    resp = client.get("/cases/REQ-2041/verify")
    _check("GET /verify returns 200", resp.status_code == 200, got=resp.status_code)
    body = resp.json()
    _check("verified = True", body.get("verified") is True, got=body.get("verified"))
    _check("has_authorization = True",
           body.get("has_authorization") is True, got=body.get("has_authorization"))
    _check("message mentions 'confirmed'",
           "confirmed" in (body.get("message") or "").lower(),
           got=body.get("message"))


# ── PATH C — Tamper detection ─────────────────────────────────────────────────

def test_tamper_detection() -> None:
    print()
    print(_SEP)
    print("  PATH C — TAMPER DETECTION (mutate package → verify_authorization=False)")
    print(_SEP)

    # Load the real stored package directly (raw DB read, not via HTTP)
    pkg = case_store.get_evidence_package("REQ-2041")
    assert pkg is not None, "Package must be stored from PATH A"
    _check("stored package has human_authorization",
           pkg.get("human_authorization") is not None)

    # ── Tamper 1: mutate a risk_score ──────────────────────────────────────────
    tampered1 = copy.deepcopy(pkg)
    for ev in tampered1["agent_evidence"]:
        if ev["agent_name"] == "stress_test" and ev.get("evidence", {}).get("risk_metrics"):
            ev["evidence"]["risk_metrics"]["risk_score"] = 99   # was 38
    result1 = authorization_signer.verify_authorization(tampered1)
    _check("tampered risk_score=99 → verified=False", result1 is False, got=result1)
    if result1 is False:
        print(f"    *** TAMPER DETECTED → verified=False (risk_score 38→99) ***")

    # ── Tamper 2: change a KYC verdict ────────────────────────────────────────
    tampered2 = copy.deepcopy(pkg)
    for ev in tampered2["agent_evidence"]:
        if ev["agent_name"] == "kyc_guardian":
            ev["verdict"] = "halt"   # was "pass"
    result2 = authorization_signer.verify_authorization(tampered2)
    _check("tampered KYC verdict pass→halt → verified=False", result2 is False, got=result2)
    if result2 is False:
        print(f"    *** TAMPER DETECTED → verified=False (KYC verdict pass→halt) ***")

    # ── Tamper 3: change the rationale text ───────────────────────────────────
    tampered3 = copy.deepcopy(pkg)
    tampered3["human_authorization"]["decision_rationale"] = "Backdated approval."
    result3 = authorization_signer.verify_authorization(tampered3)
    _check("tampered rationale → verified=False", result3 is False, got=result3)
    if result3 is False:
        print(f"    *** TAMPER DETECTED → verified=False (rationale altered) ***")

    # ── Clean package still verifies ──────────────────────────────────────────
    result_clean = authorization_signer.verify_authorization(pkg)
    _check("original (unmodified) package → verified=True",
           result_clean is True, got=result_clean)


# ── PATH D — Reject ───────────────────────────────────────────────────────────

def test_reject(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH D — REJECT (REQ-2042, Sofia Andreou — different case)")
    print(_SEP)

    _set_overrides(_ALL_PASS)
    try:
        _run_to_awaiting(client, "REQ-2042")

        resp = client.post("/cases/REQ-2042/authorize", json={
            "decision":       "reject",
            "rationale":      "Source of funds documentation insufficient for EUR 800K threshold.",
            "signatory_name": "Nevine AKF",
            "signatory_role": "Head of Digital Assets",
        })
        _check("POST /authorize {reject} returns 200",
               resp.status_code == 200, got=resp.status_code)
        body = resp.json()
        _check("response.status = rejected", body.get("status") == "rejected",
               got=body.get("status"))

        auth = body.get("human_authorization", {})
        _check("decision = rejected", auth.get("decision") == "rejected",
               got=auth.get("decision"))
        _check("rejection is also signed (authorization_signature present)",
               len(auth.get("authorization_signature") or "") > 32,
               got=len(auth.get("authorization_signature") or ""))
        _check("rejection authorization_hash starts with sha256:",
               (auth.get("authorization_hash") or "").startswith("sha256:"),
               got=(auth.get("authorization_hash") or "")[:24])

        pkg = client.get("/cases/REQ-2042/package").json()
        _check("package.case_summary.final_decision = rejected",
               pkg["case_summary"]["final_decision"] == "rejected",
               got=pkg["case_summary"]["final_decision"])

        # Verify the reject package also verifies clean
        verified = client.get("/cases/REQ-2042/verify").json()
        _check("GET /verify on rejected package → verified=True",
               verified.get("verified") is True, got=verified.get("verified"))

    finally:
        _clear_overrides()


# ── PATH E — Halted case cannot be authorized ─────────────────────────────────

def test_cannot_authorize_halted(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH E — HALTED case cannot be authorized (REQ-2043, Viktor Petrov)")
    print(_SEP)

    _set_overrides(_KYC_HALT)
    try:
        # Run Viktor through the pipeline → status = halted
        resp = client.post("/cases/REQ-2043/run")
        _check("POST /run Viktor returns 202", resp.status_code == 202,
               got=resp.status_code)
        s = client.get("/cases/REQ-2043/status").json()
        _check("Viktor status = halted after pipeline",
               s.get("status") == "halted", got=s.get("status"))

        # Try to authorize → 409
        auth_resp = client.post("/cases/REQ-2043/authorize", json={
            "decision":       "approve",
            "rationale":      "Trying to bypass the KYC halt.",
            "signatory_name": "Nevine AKF",
            "signatory_role": "Head of Digital Assets",
        })
        _check("POST /authorize on halted case → 409",
               auth_resp.status_code == 409, got=auth_resp.status_code)
        detail = auth_resp.json().get("detail", "")
        _check("409 detail mentions compliance investigation",
               "compliance investigation" in detail.lower(),
               got=detail[:90])

    finally:
        _clear_overrides()


# ── PATH F — Double-sign blocked ──────────────────────────────────────────────

def test_double_sign_blocked(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH F — DOUBLE-SIGN blocked (second authorize on REQ-2041 → 409)")
    print(_SEP)

    resp = client.post("/cases/REQ-2041/authorize", json={
        "decision":       "reject",
        "rationale":      "Attempt to override the prior signed approval.",
        "signatory_name": "Nevine AKF",
        "signatory_role": "Head of Digital Assets",
    })
    _check("second POST /authorize → 409 (decision already recorded)",
           resp.status_code == 409, got=resp.status_code)
    detail = resp.json().get("detail", "")
    _check("409 detail mentions 'already recorded'",
           "already recorded" in detail.lower() or "decision" in detail.lower(),
           got=detail[:90])


# ── PATH G — Persistence check ────────────────────────────────────────────────

def test_persistence() -> None:
    print()
    print(_SEP)
    print("  PATH G — PERSISTENCE (fresh DB reads, not memory)")
    print(_SEP)

    # REQ-2041 — approved
    row = case_store.get_case("REQ-2041")
    _check("get_case('REQ-2041') returns non-None", row is not None)
    if row:
        _check("DB: status = authorized", row["status"] == "authorized",
               got=row["status"])
        _check("DB: decision = approved", row["decision"] == "approved",
               got=row["decision"])
        _check("DB: decision_by = Nevine AKF",
               row["decision_by"] == "Nevine AKF", got=row["decision_by"])
        _check("DB: esignature_hash starts with sha256:",
               (row.get("esignature_hash") or "").startswith("sha256:"),
               got=(row.get("esignature_hash") or "")[:24])
        _check("DB: completed_at is non-null", bool(row.get("completed_at")),
               got=row.get("completed_at"))

        pkg = json.loads(row["evidence_package"])
        auth_in_pkg = pkg.get("human_authorization") or {}
        _check("DB: evidence_package.human_authorization is non-null",
               bool(auth_in_pkg))
        _check("DB: evidence_package.human_authorization.decision = approved",
               auth_in_pkg.get("decision") == "approved",
               got=auth_in_pkg.get("decision"))
        _check("DB: evidence_package.case_summary.final_decision = approved",
               pkg["case_summary"]["final_decision"] == "approved",
               got=pkg["case_summary"]["final_decision"])
        _check("DB: authorization_signature stored in package JSON",
               len(auth_in_pkg.get("authorization_signature") or "") > 32)

    # REQ-2042 — rejected
    row2 = case_store.get_case("REQ-2042")
    _check("get_case('REQ-2042') returns non-None", row2 is not None)
    if row2:
        _check("DB: REQ-2042 decision = rejected", row2["decision"] == "rejected",
               got=row2["decision"])
        _check("DB: REQ-2042 status = rejected", row2["status"] == "rejected",
               got=row2["status"])


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY — Human Authorization Test Suite (Phase 1 Final Step)")
    print("  Two-layer integrity: Layer 1 (ConsensusSigner) + Layer 2 (AuthSigner).")
    print("  Both ECDSA seals are REAL. Agents are mocked.")
    print(f"  Test DB:  {_TMP_DB.name}")
    print(f"  Test key: {_TMP_KEY.name}")
    print(_SEP2)

    with TestClient(app) as client:
        test_approve(client)              # A
        test_verify_passes(client)        # B
        test_tamper_detection()           # C (direct crypto, no HTTP)
        test_reject(client)               # D
        test_cannot_authorize_halted(client)  # E
        test_double_sign_blocked(client)  # F
        test_persistence()                # G (raw DB reads)

    # ── Summary ────────────────────────────────────────────────────────────────
    n_checks = len(_checks)
    n_fail   = len(_failures)
    n_pass   = n_checks - n_fail

    print()
    print(_SEP2)
    if not _failures:
        print(f"  [OK]  All {n_checks} assertions passed.")
    else:
        print(f"  {n_pass}/{n_checks} passed. {n_fail} FAILED:")
        for f in _failures:
            print(f"    [FAIL]  {f}")
    print(_SEP2)

    # ── Print one signed human_authorization block ─────────────────────────────
    print()
    print(_SEP2)
    print("  SIGNED HUMAN AUTHORIZATION BLOCK — REQ-2041 (from SQLite)")
    print(_SEP2)
    row = case_store.get_case("REQ-2041")
    if row:
        pkg = json.loads(row["evidence_package"])
        auth = pkg.get("human_authorization") or {}
        print(f"  decision              : {auth.get('decision')}")
        print(f"  decision_rationale    : {(auth.get('decision_rationale') or '')[:70]}…")
        print(f"  signatory_name        : {auth.get('signatory_name')}")
        print(f"  signatory_role        : {auth.get('signatory_role')}")
        print(f"  signed_at             : {auth.get('signed_at')}")
        print(f"  curve                 : {auth.get('curve')}")
        print(f"  authorization_hash    : {(auth.get('authorization_hash') or '')[:32]}…")
        print(f"  authorization_signature: {(auth.get('authorization_signature') or '')[:32]}…")
        print(f"  public_key            : {(auth.get('public_key') or '')[:32]}…")
        print(f"  annotations           : {auth.get('annotations')}")
    print()

    # ── Cleanup ────────────────────────────────────────────────────────────────
    for path in (_TMP_DB.name, _TMP_KEY.name):
        try:
            os.unlink(path)
        except OSError:
            pass

    sys.exit(1 if _failures else 0)
