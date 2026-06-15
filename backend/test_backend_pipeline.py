"""
backend/test_backend_pipeline.py
Brightuity — Backend pipeline integration test.

Tests the full HTTP layer end-to-end using FastAPI's TestClient.
No real LLM calls: agents are replaced with the same mock functions used in
agents/governance_audit/test_governance_audit.py. ConsensusSigner is REAL
(ECDSA) on the happy path — the seal hash in the evidence package is genuine.

Test paths:
  PATH A — Happy path        (REQ-2041, Marcus Weber, all-pass)
  PATH B — KYC halt          (REQ-2043, Viktor Petrov, WL-001 PEP match)
  PATH C — Idempotency       (second POST /run without force → 409)
  PATH D — Force re-run      (force=true after terminal state → allowed)
  PATH E — Illegal transition (state machine rejects invalid direct jump)
  PATH F — Persistence check (fresh DB read confirms data survived)
  PATH G — Existing endpoints (GET /health, /cases, /cases/{id} still work)

Run:
    python -m backend.test_backend_pipeline
  or:
    python backend/test_backend_pipeline.py

Important: uses a temporary SQLite file (not the production DB).
           Sets CASES_DB_PATH env var before any backend imports.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile

# ── Set test DB path BEFORE any backend imports ────────────────────────────────
# get_db_path() reads os.environ at call time, so this is picked up when
# init_db() fires during TestClient startup. Never touches production DB.
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["CASES_DB_PATH"] = _TMP_DB.name

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# ── UTF-8 output ───────────────────────────────────────────────────────────────
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── Backend imports (after env var is set) ─────────────────────────────────────
from starlette.testclient import TestClient

from backend.main import app, _pipeline_agent_overrides, _pipeline_synthesis_override
from backend import case_state, case_store

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


# ── Mock agent functions (copied from test_governance_audit — no LLM) ──────────

def _mock_doc_pass(cr: dict) -> dict:
    return {
        "agent": "doc_auditor", "verdict": "pass",
        "summary": "All documents verified. Title deed clean.",
        "issues_found": [],
        "model_used": "mock", "was_fallback": False, "latency_ms": 100,
    }


def _mock_kyc_pass(cr: dict) -> dict:
    return {
        "agent": "kyc_guardian", "verdict": "pass",
        "summary": "Identity verified. No PEP match. No sanctions hit.",
        "flags_raised": [],
        "model_used": "mock", "was_fallback": False, "latency_ms": 120,
        "screening_result": {
            "matched": False, "match_type": None, "matched_entry": None,
            "match_score": 0.0,
            "sources_checked": [
                "EU Consolidated Sanctions List", "FATF PEP Register",
                "National PEP Register (CY/RU/BY/UA)",
                "OFAC SDN List (EU mirror)", "UN Security Council Consolidated List",
            ],
        },
    }


def _mock_kyc_halt(cr: dict) -> dict:
    return {
        "agent": "kyc_guardian", "verdict": "halt",
        "summary": (
            "Confirmed PEP match (Viktor Petrov, WL-001, FATF PEP Register) "
            "combined with unverifiable offshore source of funds."
        ),
        "flags_raised": [
            "Confirmed deterministic PEP match — WL-001 on FATF PEP Register",
            "Source of funds: unverifiable offshore structures",
        ],
        "model_used": "mock", "was_fallback": False, "latency_ms": 130,
        "screening_result": {
            "matched": True, "match_type": "pep",
            "matched_entry": {
                "id": "WL-001", "name": "Viktor Petrov", "type": "pep",
                "country": "Cyprus", "source": "FATF PEP Register",
                "listed_since": "2023-11-14",
                "notes": "Former director of state-owned energy enterprise.",
            },
            "match_score": 1.0,
            "sources_checked": [
                "EU Consolidated Sanctions List", "FATF PEP Register",
                "National PEP Register (CY/RU/BY/UA)",
                "OFAC SDN List (EU mirror)", "UN Security Council Consolidated List",
            ],
        },
    }


def _mock_compliance_pass(cr: dict) -> dict:
    return {
        "agent": "dynamic_compliance", "verdict": "pass",
        "summary": "MiCA Art. 17 & 68 compliant. Jurisdiction: Germany (EU).",
        "jurisdiction": "Germany (EU)",
        "citations": ["MiCA Art. 17", "MiCA Art. 68"],
        "concerns": [], "retrieved_k": 3,
        "model_used": "mock", "was_fallback": False, "latency_ms": 140,
    }


def _mock_stress_pass(cr: dict) -> dict:
    return {
        "agent": "stress_test", "verdict": "pass",
        "summary": "Risk score 38/100 (medium). Worst-case EUR 1,440,000.",
        "risk_level": "medium",
        "risk_factors": ["Commercial property illiquidity 10%"],
        "model_used": "mock", "was_fallback": False, "latency_ms": 110,
        "risk_metrics": {
            "base_valuation": 2_000_000.0, "asset_type": "Commercial Property",
            "illiquidity_discount": 0.10, "market_volatility": 0.12,
            "market_stress_scenarios": {
                "market_downturn_20pct_eur": 1_600_000,
                "liquidity_crisis_eur":      1_440_000,
                "interest_rate_shock_eur":   1_640_000,
            },
            "stressed_value_range": {
                "worst_case_eur": 1_440_000,
                "base_case_eur":  2_000_000,
                "best_case_eur":  2_200_000,
            },
            "score_components": {
                "illiquidity_score": 13, "volatility_score": 17,
                "concentration_score": 8, "flags_score": 0,
            },
            "risk_score": 38, "risk_level": "medium", "verdict": "pass",
            "risk_factors": ["Commercial property illiquidity (10%)"],
            "methodology": "risk_score = 13+17+8+0 = 38/100",
        },
    }


def _mock_tokenizer_pass(cr: dict) -> dict:
    return {
        "agent": "asset_tokenizer", "verdict": "pass",
        "summary": "ERC-3643 T-REX. 2,000 tokens at EUR 1,000.",
        "token_standard": "ERC-3643 T-REX",
        "total_tokens": 2_000,
        "value_per_token_eur": 1_000.0,
        "structure_notes": ["EU qualified investors only"],
        "model_used": "mock", "was_fallback": False, "latency_ms": 90,
    }


def _mock_synthesis(dr: dict) -> dict:
    status = dr.get("pipeline_status", "unknown")
    if status == "approved_pending_human":
        headline = "APPROVED PENDING HUMAN — all 5 gates cleared."
    else:
        headline = f"HALTED/BLOCKED — pipeline status: {status}."
    return {
        "headline":          headline,
        "decisive_factor":   "Mock synthesis.",
        "per_agent_summary": ["Mock per-agent summary."],
        "recommendation":    "Human review required.",
        "source":            "mock",
        "model_used":        "none",
        "was_fallback":      False,
        "latency_ms":        0,
    }


_ALL_PASS_OVERRIDES: dict = {
    "doc_auditor":        _mock_doc_pass,
    "kyc_guardian":       _mock_kyc_pass,
    "dynamic_compliance": _mock_compliance_pass,
    "stress_test":        _mock_stress_pass,
    "asset_tokenizer":    _mock_tokenizer_pass,
}

_KYC_HALT_OVERRIDES: dict = {
    "doc_auditor":        _mock_doc_pass,
    "kyc_guardian":       _mock_kyc_halt,
    "dynamic_compliance": _mock_compliance_pass,
    "stress_test":        _mock_stress_pass,
    "asset_tokenizer":    _mock_tokenizer_pass,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _set_overrides(agent_overrides: dict | None, synthesis) -> None:
    app.dependency_overrides[_pipeline_agent_overrides] = lambda: agent_overrides
    app.dependency_overrides[_pipeline_synthesis_override] = lambda: synthesis


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


# ── PATH A — Happy path ───────────────────────────────────────────────────────

def test_happy_path(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH A — Happy path (REQ-2041, Marcus Weber, all-pass)")
    print("           ConsensusSigner is REAL. Agents are mocked.")
    print(_SEP)

    _set_overrides(_ALL_PASS_OVERRIDES, _mock_synthesis)
    try:
        # POST /run → 202
        resp = client.post("/cases/REQ-2041/run")
        _check("POST /run returns 202 Accepted", resp.status_code == 202,
               got=resp.status_code)
        body = resp.json()
        _check("response.status = processing", body.get("status") == "processing",
               got=body.get("status"))
        _check("response.request_id = REQ-2041", body.get("request_id") == "REQ-2041",
               got=body.get("request_id"))

        # Background task runs synchronously in TestClient before the response
        # is returned — status should be awaiting_decision already.
        status_resp = client.get("/cases/REQ-2041/status")
        _check("GET /status returns 200", status_resp.status_code == 200,
               got=status_resp.status_code)
        s = status_resp.json()
        _check("status = awaiting_decision after pipeline",
               s.get("status") == "awaiting_decision", got=s.get("status"))
        _check("pipeline_status = approved_pending_human",
               s.get("pipeline_status") == "approved_pending_human",
               got=s.get("pipeline_status"))
        _check("gate_outcome = pass", s.get("gate_outcome") == "pass",
               got=s.get("gate_outcome"))
        _check("seal_status = sealed", s.get("seal_status") == "sealed",
               got=s.get("seal_status"))
        _check("consensus_hash starts with sha256:",
               (s.get("consensus_hash") or "").startswith("sha256:"),
               got=(s.get("consensus_hash") or "")[:20])

        # GET /package → evidence package
        pkg_resp = client.get("/cases/REQ-2041/package")
        _check("GET /package returns 200", pkg_resp.status_code == 200,
               got=pkg_resp.status_code)
        pkg = pkg_resp.json()

        # All 8 sections present
        for section in ("package_metadata", "case_summary", "decision_lineage",
                        "agent_evidence", "governance_gate", "consensus_seal",
                        "explainability", "human_authorization"):
            _check(f"package section '{section}' present", section in pkg)

        # Package metadata
        pm = pkg["package_metadata"]
        _check("package_id starts with EVP-REQ-2041",
               pm["package_id"].startswith("EVP-REQ-2041"),
               got=pm["package_id"][:25])
        _check("schema_version = 1.0", pm["schema_version"] == "1.0")

        # Case summary (non-PII only)
        cs = pkg["case_summary"]
        _check("case_summary.pipeline_status = approved_pending_human",
               cs["pipeline_status"] == "approved_pending_human",
               got=cs["pipeline_status"])
        _check("case_summary.final_decision is None",
               cs["final_decision"] is None)

        # KYC evidence — watchlist provenance
        ev_list = pkg["agent_evidence"]
        kyc_ev = next((e for e in ev_list if e["agent_name"] == "kyc_guardian"), None)
        _check("kyc_guardian in agent_evidence", kyc_ev is not None)
        if kyc_ev:
            sr = kyc_ev["evidence"].get("screening_result")
            _check("KYC screening_result.matched = False (no watchlist hit)",
                   sr is not None and sr["matched"] is False, got=sr and sr["matched"])

        # Stress-test evidence — risk_metrics provenance
        stress_ev = next((e for e in ev_list if e["agent_name"] == "stress_test"), None)
        _check("stress_test in agent_evidence", stress_ev is not None)
        if stress_ev:
            rm = stress_ev["evidence"].get("risk_metrics")
            _check("stress risk_metrics.risk_score = 38",
                   rm is not None and rm.get("risk_score") == 38,
                   got=rm and rm.get("risk_score"))
            svr = (rm or {}).get("stressed_value_range", {})
            _check("stressed_value_range.worst_case_eur = 1,440,000",
                   svr.get("worst_case_eur") == 1_440_000,
                   got=svr.get("worst_case_eur"))

        # Consensus seal — real ECDSA
        seal = pkg["consensus_seal"]
        _check("consensus_seal.status = sealed", seal["status"] == "sealed",
               got=seal["status"])
        _check("consensus_seal.canonical_hash starts with sha256:",
               (seal.get("canonical_hash") or "").startswith("sha256:"),
               got=(seal.get("canonical_hash") or "")[:20])
        _check("consensus_seal.signature present",
               bool(seal.get("signature")))

        # human_authorization not yet signed
        _check("human_authorization is None", pkg["human_authorization"] is None)

    finally:
        _clear_overrides()


# ── PATH B — KYC halt ─────────────────────────────────────────────────────────

def test_kyc_halt(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH B — KYC halt (REQ-2043, Viktor Petrov, WL-001 PEP)")
    print(_SEP)

    _set_overrides(_KYC_HALT_OVERRIDES, _mock_synthesis)
    try:
        resp = client.post("/cases/REQ-2043/run")
        _check("POST /run returns 202", resp.status_code == 202,
               got=resp.status_code)

        s = client.get("/cases/REQ-2043/status").json()
        _check("status = halted (pipeline halted_kyc)",
               s.get("status") == "halted", got=s.get("status"))
        _check("pipeline_status = halted_kyc",
               s.get("pipeline_status") == "halted_kyc",
               got=s.get("pipeline_status"))
        _check("seal_status = blocked (KYC halt blocks ECDSA seal)",
               s.get("seal_status") == "blocked", got=s.get("seal_status"))
        _check("consensus_hash is None (not sealed)",
               s.get("consensus_hash") is None, got=s.get("consensus_hash"))

        pkg = client.get("/cases/REQ-2043/package").json()
        cs  = pkg["case_summary"]
        _check("package case_summary.pipeline_status = halted_kyc",
               cs["pipeline_status"] == "halted_kyc", got=cs["pipeline_status"])

        ev_list = pkg["agent_evidence"]
        kyc_ev  = next((e for e in ev_list if e["agent_name"] == "kyc_guardian"), None)
        _check("kyc_guardian in evidence", kyc_ev is not None)
        if kyc_ev:
            _check("KYC verdict = halt", kyc_ev["verdict"] == "halt",
                   got=kyc_ev["verdict"])
            sr = kyc_ev["evidence"].get("screening_result")
            _check("screening_result.matched = True",
                   sr is not None and sr["matched"] is True, got=sr and sr["matched"])
            _check("matched_entry.id = WL-001",
                   (sr or {}).get("matched_entry", {}).get("id") == "WL-001",
                   got=(sr or {}).get("matched_entry", {}).get("id"))

        ev_names = [e["agent_name"] for e in ev_list]
        _check("asset_tokenizer absent (skipped on halt)",
               "asset_tokenizer" not in ev_names, got=ev_names)

        seal = pkg["consensus_seal"]
        _check("seal.status = blocked", seal["status"] == "blocked",
               got=seal["status"])
        _check("seal.canonical_hash is None", seal.get("canonical_hash") is None)
        _check("human_authorization is None", pkg["human_authorization"] is None)

    finally:
        _clear_overrides()


# ── PATH C — Idempotency ──────────────────────────────────────────────────────

def test_idempotency(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH C — Idempotency (second POST /run without force → 409)")
    print(_SEP)

    _set_overrides(_ALL_PASS_OVERRIDES, _mock_synthesis)
    try:
        # REQ-2041 is already awaiting_decision from PATH A
        resp2 = client.post("/cases/REQ-2041/run")
        _check("second POST /run (no force) returns 409 Conflict",
               resp2.status_code == 409, got=resp2.status_code)
        detail = resp2.json().get("detail", "")
        _check("409 detail mentions awaiting_decision",
               "awaiting_decision" in detail or "force" in detail,
               got=detail[:80])

    finally:
        _clear_overrides()


# ── PATH D — Force re-run ─────────────────────────────────────────────────────

def test_force_rerun(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH D — Force re-run (force=true on awaiting_decision → allowed)")
    print(_SEP)

    _set_overrides(_ALL_PASS_OVERRIDES, _mock_synthesis)
    try:
        resp = client.post("/cases/REQ-2041/run?force=true")
        _check("POST /run?force=true returns 202 on awaiting_decision case",
               resp.status_code == 202, got=resp.status_code)

        s = client.get("/cases/REQ-2041/status").json()
        _check("status returns to awaiting_decision after force re-run",
               s.get("status") == "awaiting_decision", got=s.get("status"))

    finally:
        _clear_overrides()


# ── PATH E — Illegal state transition ─────────────────────────────────────────

def test_illegal_transition() -> None:
    print()
    print(_SEP)
    print("  PATH E — Illegal transition (state machine rejects invalid jump)")
    print(_SEP)

    raised = False
    try:
        case_state.validate_transition("pending", "authorized")
    except case_state.InvalidTransitionError as exc:
        raised = True
        _check("InvalidTransitionError raised for pending→authorized", True)
        _check("error message mentions 'authorized'", "authorized" in str(exc),
               got=str(exc)[:80])
    _check("exception was raised", raised)

    raised2 = False
    try:
        case_state.validate_transition("authorized", "processing")
    except case_state.InvalidTransitionError:
        raised2 = True
    _check("InvalidTransitionError raised for terminal authorized→processing", raised2)

    # can_run on processing → not allowed even with force
    allowed, reason = case_state.can_run("processing", force=True)
    _check("can_run('processing', force=True) → False (can't run two in parallel)",
           not allowed, got=allowed)
    _check("reason mentions 'already running'", "already running" in reason.lower(),
           got=reason[:60])

    # can_run on terminal authorized → not allowed even with force
    allowed2, reason2 = case_state.can_run("authorized", force=True)
    _check("can_run('authorized', force=True) → False (terminal human decision)",
           not allowed2, got=allowed2)


# ── PATH F — Persistence check ────────────────────────────────────────────────

def test_persistence() -> None:
    print()
    print(_SEP)
    print("  PATH F — Persistence check (fresh DB read, proves SQLite not memory)")
    print(_SEP)

    # Fresh DB read via case_store (not via HTTP) — proves SQLite actually stored it
    case = case_store.get_case("REQ-2041")
    _check("get_case('REQ-2041') returns non-None", case is not None)
    if case:
        _check("DB row: status = awaiting_decision",
               case["status"] == "awaiting_decision", got=case["status"])
        _check("DB row: pipeline_status = approved_pending_human",
               case["pipeline_status"] == "approved_pending_human",
               got=case["pipeline_status"])
        _check("DB row: seal_status = sealed",
               case["seal_status"] == "sealed", got=case["seal_status"])
        _check("DB row: consensus_hash starts with sha256:",
               (case.get("consensus_hash") or "").startswith("sha256:"),
               got=(case.get("consensus_hash") or "")[:20])
        _check("DB row: evidence_package column is non-empty JSON",
               bool(case.get("evidence_package")),
               got=len(case.get("evidence_package") or ""))
        _check("DB row: decision_record_json column is non-empty JSON",
               bool(case.get("decision_record_json")),
               got=len(case.get("decision_record_json") or ""))

        # Parse the JSON blobs — they must be valid JSON
        pkg_parsed = json.loads(case["evidence_package"])
        _check("evidence_package JSON parses to dict",
               isinstance(pkg_parsed, dict), got=type(pkg_parsed).__name__)
        _check("parsed package has 8 top-level sections",
               len(pkg_parsed) == 8, got=len(pkg_parsed))

    # Viktor Petrov case
    case_v = case_store.get_case("REQ-2043")
    _check("get_case('REQ-2043') returns non-None", case_v is not None)
    if case_v:
        _check("Viktor DB row: status = halted",
               case_v["status"] == "halted", got=case_v["status"])
        _check("Viktor DB row: seal_status = blocked",
               case_v["seal_status"] == "blocked", got=case_v["seal_status"])
        _check("Viktor DB row: consensus_hash is None",
               case_v.get("consensus_hash") is None, got=case_v.get("consensus_hash"))


# ── PATH G — Existing endpoints still work ────────────────────────────────────

def test_existing_endpoints(client: TestClient) -> None:
    print()
    print(_SEP)
    print("  PATH G — Existing endpoints (GET /health, /cases, /cases/{id})")
    print(_SEP)

    # /health
    h = client.get("/health")
    _check("GET /health returns 200", h.status_code == 200, got=h.status_code)
    _check("health.status = ok", h.json().get("status") == "ok",
           got=h.json().get("status"))
    _check("health.cases_loaded is a positive int",
           isinstance(h.json().get("cases_loaded"), int) and h.json().get("cases_loaded") > 0,
           got=h.json().get("cases_loaded"))

    # /cases (default: pending queue)
    cases = client.get("/cases")
    _check("GET /cases returns 200", cases.status_code == 200, got=cases.status_code)
    cards = cases.json()
    _check("GET /cases returns a list", isinstance(cards, list), got=type(cards).__name__)
    if cards:
        card = cards[0]
        _check("card has no 'expected_outcome' field",
               "expected_outcome" not in card, got=list(card.keys()))
        _check("card has 'request_id' field", "request_id" in card)
        _check("card has 'full_name' field", "full_name" in card)
        _check("card has no 'passport_number' field",
               "passport_number" not in card)

    # /cases/{request_id}
    detail = client.get("/cases/REQ-2041")
    _check("GET /cases/REQ-2041 returns 200", detail.status_code == 200,
           got=detail.status_code)
    d = detail.json()
    _check("detail has 'asset_detail' field", "asset_detail" in d)
    _check("detail has no 'expected_outcome' field",
           "expected_outcome" not in d, got=list(d.keys()))

    # 404 on unknown case
    miss = client.get("/cases/REQ-9999")
    _check("GET /cases/REQ-9999 returns 404", miss.status_code == 404,
           got=miss.status_code)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY — Backend Pipeline Test Suite")
    print("  FastAPI TestClient + mocked agents (no real LLM calls).")
    print("  ConsensusSigner is REAL (ECDSA) on PATH A and D.")
    print(f"  Test DB: {_TMP_DB.name}")
    print(_SEP2)

    with TestClient(app) as client:
        # startup fires → init_db() runs against the temp DB
        test_existing_endpoints(client)   # G first so DB is clean
        test_happy_path(client)           # A
        test_kyc_halt(client)             # B
        test_idempotency(client)          # C (REQ-2041 is now awaiting_decision)
        test_force_rerun(client)          # D
        test_illegal_transition()         # E (no HTTP; pure state machine)
        test_persistence()                # F (raw DB reads, no HTTP)

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

    # ── Print one persisted row for verification ───────────────────────────────
    print()
    print(_SEP2)
    print("  PERSISTED CASE ROW — REQ-2041 (from SQLite, not memory)")
    print(_SEP2)
    row = case_store.get_case("REQ-2041")
    if row:
        pkg_preview = json.loads(row["evidence_package"] or "{}")
        print(f"  request_id      : {row['request_id']}")
        print(f"  status          : {row['status']}")
        print(f"  pipeline_status : {row['pipeline_status']}")
        print(f"  gate_outcome    : {row['gate_outcome']}")
        print(f"  seal_status     : {row['seal_status']}")
        print(f"  consensus_hash  : {row['consensus_hash']}")
        print(f"  initiated_at    : {row['initiated_at']}")
        print(f"  updated_at      : {row['updated_at']}")
        print(f"  evidence_package: {len(row.get('evidence_package') or '')} bytes JSON")
        print(f"  pkg sections    : {list(pkg_preview.keys())}")
        print(f"  package_id      : {pkg_preview.get('package_metadata', {}).get('package_id', '')}")
    print()

    # ── Cleanup ────────────────────────────────────────────────────────────────
    try:
        os.unlink(_TMP_DB.name)
    except OSError:
        pass

    sys.exit(1 if _failures else 0)
