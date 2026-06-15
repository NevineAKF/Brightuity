"""
agents/governance_audit/test_governance_audit.py
Brightuity — Test suite for the Governance & Audit Agent.

Runs two pipelines through the orchestrator using mocked agent functions
(no real LLM calls), then assembles and validates the Evidence Package
for each path:

  PATH A — Happy path  (REQ-2041, Marcus Weber)
    All 5 agents pass. Seal is real ECDSA (ConsensusSigner is NOT mocked).
    Asserts: 8 sections present, KYC no-match provenance, stress risk_metrics,
             real sha256 hash in consensus_seal, human_authorization=None.
    Prints: full pretty JSON of the assembled package.

  PATH B — KYC halt    (REQ-2043, Viktor Petrov)
    KYC Guardian halts with WL-001 PEP match. Tokenizer skipped.
    Seal blocked. Asserts: pipeline_status=halted_kyc, KYC evidence shows
    WL-001 deterministic match, human_authorization=None.

Assertions are collected and reported at the end. No real LLM calls anywhere.
ConsensusSigner is real in both paths (ECDSA seal / blocked result).

Run:
    python -m agents.governance_audit.test_governance_audit
  or:
    python agents/governance_audit/test_governance_audit.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,    # suppress INFO logs from orchestrator during test
    stream=sys.stderr,
)

# ── UTF-8 output ───────────────────────────────────────────────────────────────
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from agents.orchestrator.orchestrator import run_pipeline
from agents.governance_audit.logic import assemble_evidence_package

# ── Symbols ────────────────────────────────────────────────────────────────────
_OK   = "OK"
_FAIL = "FAIL"
_SEP  = "-" * 72
_SEP2 = "=" * 72

# ── Shared mock client records (non-PII safe fields only) ─────────────────────

_CLIENT_WEBER: dict = {
    "request_id":      "REQ-2041",
    "client_id":       "CLT-0001",
    "asset_type":      "Commercial Property",
    "asset_detail":    "Office building, Berlin",
    "asset_value_eur": 2_000_000,
    "submitted_at":    "2026-06-09T13:29:00",
    "nationality":     "Germany",
    "full_name":       "Marcus Weber",       # used by KYC screening (deterministic)
    "kyc_status":      "clean",
    "kyc_flags":       [],
    "source_of_funds": "Salary accumulation",
    "source_verifiable": True,
    "risk_flags":      [],
}

_CLIENT_PETROV: dict = {
    "request_id":      "REQ-2043",
    "client_id":       "CLT-0003",
    "asset_type":      "Luxury Villa",
    "asset_detail":    "Seafront estate, Limassol",
    "asset_value_eur": 5_000_000,
    "submitted_at":    "2026-06-11T06:11:00",
    "nationality":     "Cyprus",
    "full_name":       "Viktor Petrov",      # triggers WL-001 PEP match
    "kyc_status":      "pep_match",
    "kyc_flags":       ["PEP match — politically exposed network"],
    "source_of_funds": "Unverifiable offshore structures",
    "source_verifiable": False,
    "risk_flags":      [],
}

# ── Mock agent functions (no LLM, deterministic responses) ────────────────────

def _mock_doc_pass(cr: dict) -> dict:
    return {
        "agent": "doc_auditor", "verdict": "pass",
        "summary": "All documents verified. Title deed clean, ownership chain complete.",
        "issues_found": [],
        "model_used": "mock", "was_fallback": False, "latency_ms": 100,
    }

def _mock_kyc_pass(cr: dict) -> dict:
    return {
        "agent": "kyc_guardian", "verdict": "pass",
        "summary": "Identity verified. No PEP match. No sanctions hit. "
                   "Source of funds (salary accumulation) verified.",
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
            "Confirmed PEP match (Viktor Petrov, WL-001, FATF PEP Register) combined "
            "with unverifiable offshore source of funds — mandatory hard stop under "
            "AMLD5 Article 20 EDD requirements."
        ),
        "flags_raised": [
            "Confirmed deterministic PEP match — WL-001 on FATF PEP Register",
            "Source of funds: unverifiable offshore structures — AML placement/layering indicator",
        ],
        "model_used": "mock", "was_fallback": False, "latency_ms": 130,
        "screening_result": {
            "matched": True,
            "match_type": "pep",
            "matched_entry": {
                "id": "WL-001",
                "name": "Viktor Petrov",
                "type": "pep",
                "country": "Cyprus",
                "source": "FATF PEP Register",
                "listed_since": "2023-11-14",
                "notes": (
                    "Former director of state-owned energy enterprise; "
                    "beneficiary of Cyprus investment programme; "
                    "member of politically exposed network with undisclosed "
                    "beneficial ownership structures"
                ),
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
        "summary": "MiCA Art. 17 & 68 compliant. No cross-border restrictions. Jurisdiction: Germany (EU).",
        "jurisdiction": "Germany (EU)",
        "citations": ["MiCA Art. 17", "MiCA Art. 68", "EU AMLD5 Art. 20"],
        "concerns": [], "retrieved_k": 3,
        "model_used": "mock", "was_fallback": False, "latency_ms": 140,
    }

def _mock_stress_pass(cr: dict) -> dict:
    return {
        "agent": "stress_test", "verdict": "pass",
        "summary": (
            "Risk score 38/100 (medium). Worst-case liquidity crisis EUR 1,440,000 "
            "(-28% vs EUR 2,000,000 base). Risk is within acceptable programme tolerance."
        ),
        "risk_level": "medium",
        "risk_factors": [
            "Illiquidity (Commercial Property): 90-180 day sale cycle; forced-sale discount 10%",
            "EUR 1,440,000 worst-case valuation — 28% haircut under combined market downturn and illiquidity",
            "Single-asset concentration: EUR 2,000,000 in one Commercial Property",
        ],
        "model_used": "mock", "was_fallback": False, "latency_ms": 110,
        "risk_metrics": {
            "base_valuation":       2_000_000.0,
            "asset_type":           "Commercial Property",
            "illiquidity_discount": 0.10,
            "market_volatility":    0.12,
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
            "risk_score": 38,
            "risk_level": "medium",
            "verdict":    "pass",
            "risk_factors": ["Commercial property illiquidity (10% forced-sale discount)"],
            "methodology": (
                "risk_score = illiquidity_score(13) + volatility_score(17) "
                "+ concentration_score(8) + flags_score(0) = 38/100. "
                "Thresholds: <30=low/pass, 30-59=medium/pass, 60-79=high/pass, >=80=critical/fail."
            ),
        },
    }

def _mock_tokenizer_pass(cr: dict) -> dict:
    return {
        "agent": "asset_tokenizer", "verdict": "pass",
        "summary": (
            "ERC-3643 T-REX structure. 2,000 tokens at EUR 1,000 each. "
            "Transfer restricted to EU qualified investors under MiCA."
        ),
        "token_standard": "ERC-3643 T-REX",
        "total_tokens":   2_000,
        "value_per_token_eur": 1_000.0,
        "structure_notes": [
            "Transfer restrictions: EU qualified investors only (MiCA Art. 68)",
            "Settlement: T+1 on permissioned EVM chain",
        ],
        "model_used": "mock", "was_fallback": False, "latency_ms": 90,
    }

def _mock_synthesis(dr: dict) -> dict:
    status = dr.get("pipeline_status", "unknown")
    if status == "approved_pending_human":
        headline = "APPROVED PENDING HUMAN — all 5 compliance gates cleared, ECDSA seal produced."
        decisive = "All mandatory gates (Doc, KYC, Compliance, Stress, Tokenizer) returned pass."
        rec = (
            "Pipeline cleared all compliance gates. Recommend Head of Digital Assets "
            "review the full evidence package and make the final approve/reject decision. "
            "This system does not and cannot make the final call."
        )
        per_agent = [
            "Doc Auditor: PASS — documents complete, title deed clean.",
            "KYC Guardian: PASS — no watchlist match, source of funds verified.",
            "Dynamic Compliance: PASS — MiCA Art. 17 & 68 compliant, Germany (EU).",
            "Stress-Test: PASS — risk score 38/100 (medium), within programme tolerance.",
            "Asset Tokenizer: PASS — 2,000 ERC-3643 T-REX tokens at EUR 1,000 each.",
        ]
    else:
        headline = "HALTED — KYC Guardian issued hard stop (PEP match + unverifiable offshore funds)."
        decisive = "Confirmed PEP match on FATF PEP Register (WL-001) combined with unverifiable offshore source of funds."
        rec = (
            "Pipeline halted at KYC gate. Full compliance investigation required "
            "before any further processing. Human sign-off by Head of Digital Assets "
            "is mandatory before this case can proceed."
        )
        per_agent = [
            "Doc Auditor: PASS — documents complete, clean title.",
            "KYC Guardian: HALT — WL-001 PEP match, offshore funds. Hard stop.",
            "Dynamic Compliance: PASS — jurisdiction clear (ran in parallel).",
            "Stress-Test: PASS — risk score computed (ran in parallel, advisory).",
            "Asset Tokenizer: SKIPPED — pipeline halted before tokenization.",
        ]
    return {
        "headline":          headline,
        "decisive_factor":   decisive,
        "per_agent_summary": per_agent,
        "recommendation":    rec,
        "source":            "mock",
        "model_used":        "none",
        "was_fallback":      False,
        "latency_ms":        0,
    }

# ── Assertion tracker ──────────────────────────────────────────────────────────

_failures: list[str] = []
_checks:   list[None] = []

def _check(label: str, condition: bool, got: object = None) -> None:
    _checks.append(None)
    suffix = f"  [{got}]" if got is not None else ""
    mark   = _OK if condition else _FAIL
    print(f"    [{mark}]  {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── PATH A — Happy path ───────────────────────────────────────────────────────

def test_happy_path() -> dict:
    print()
    print(_SEP)
    print("  PATH A — Happy path  (REQ-2041, Marcus Weber, all-pass)")
    print("           ConsensusSigner is REAL (ECDSA). Agents are mocked.")
    print(_SEP)

    overrides = {
        "doc_auditor":        _mock_doc_pass,
        "kyc_guardian":       _mock_kyc_pass,
        "dynamic_compliance": _mock_compliance_pass,
        "stress_test":        _mock_stress_pass,
        "asset_tokenizer":    _mock_tokenizer_pass,
    }

    decision_record, event_log = run_pipeline(
        _CLIENT_WEBER,
        _agent_overrides=overrides,
        _synthesis_override=_mock_synthesis,
    )

    pkg = assemble_evidence_package(decision_record, event_log, _CLIENT_WEBER)

    print()
    print("  STRUCTURE ASSERTIONS")

    # Top-level sections
    for section in ("package_metadata", "case_summary", "decision_lineage",
                    "agent_evidence", "governance_gate", "consensus_seal",
                    "explainability", "human_authorization"):
        _check(f"section '{section}' present", section in pkg, got=type(pkg.get(section)).__name__)

    # package_metadata
    pm = pkg["package_metadata"]
    _check("package_id starts with EVP-REQ-2041",
           pm["package_id"].startswith("EVP-REQ-2041"), got=pm["package_id"][:25])
    _check("institution is Meridian Digital Bank",
           "Meridian Digital Bank" in pm["institution"], got=pm["institution"][:30])
    _check("schema_version = 1.0", pm["schema_version"] == "1.0", got=pm["schema_version"])

    # case_summary
    cs = pkg["case_summary"]
    _check("pipeline_status = approved_pending_human",
           cs["pipeline_status"] == "approved_pending_human", got=cs["pipeline_status"])
    _check("asset_type = Commercial Property",
           cs["asset_type"] == "Commercial Property", got=cs["asset_type"])
    _check("asset_value_eur = 2,000,000",
           cs["asset_value_eur"] == 2_000_000, got=cs["asset_value_eur"])
    _check("final_decision is None (not yet signed)",
           cs["final_decision"] is None, got=cs["final_decision"])

    # decision_lineage
    lineage = pkg["decision_lineage"]
    _check("decision_lineage is non-empty", len(lineage) > 0, got=len(lineage))
    _check("lineage step 1 is pipeline_start",
           lineage[0]["event"] == "pipeline_start", got=lineage[0]["event"])
    _check("lineage steps are ordered",
           all(lineage[i]["step"] == i + 1 for i in range(len(lineage))),
           got="all sequential")
    _check("lineage contains gate_result event",
           any(e["event"] == "gate_result" for e in lineage), got="found")
    _check("lineage contains seal_complete event",
           any(e["event"] == "seal_complete" for e in lineage), got="found")

    # agent_evidence
    ev_list = pkg["agent_evidence"]
    ev_names = [e["agent_name"] for e in ev_list]
    for name in ("doc_auditor", "kyc_guardian", "dynamic_compliance", "stress_test", "asset_tokenizer"):
        _check(f"agent_evidence contains {name}", name in ev_names)

    kyc_ev = next(e for e in ev_list if e["agent_name"] == "kyc_guardian")
    _check("KYC verdict = pass", kyc_ev["verdict"] == "pass", got=kyc_ev["verdict"])
    _check("KYC role label set", "KYC" in kyc_ev["role"], got=kyc_ev["role"])
    _check("KYC evidence.screening_result present",
           "screening_result" in kyc_ev["evidence"], got="present")
    sr = kyc_ev["evidence"]["screening_result"]
    _check("KYC screening matched=False (Marcus no watchlist hit)",
           sr is not None and sr["matched"] is False, got=sr and sr["matched"])
    _check("KYC screening sources_checked is non-empty",
           sr is not None and len(sr["sources_checked"]) > 0, got=sr and len(sr["sources_checked"]))

    stress_ev = next(e for e in ev_list if e["agent_name"] == "stress_test")
    _check("Stress verdict = pass", stress_ev["verdict"] == "pass", got=stress_ev["verdict"])
    _check("Stress evidence.risk_metrics present",
           "risk_metrics" in stress_ev["evidence"], got="present")
    rm = stress_ev["evidence"]["risk_metrics"]
    _check("risk_metrics.risk_score = 38",
           rm is not None and rm.get("risk_score") == 38, got=rm and rm.get("risk_score"))
    _check("risk_metrics.stressed_value_range present",
           rm is not None and "stressed_value_range" in rm, got="present")
    svr = (rm or {}).get("stressed_value_range", {})
    _check("stressed_value_range.worst_case_eur = 1,440,000",
           svr.get("worst_case_eur") == 1_440_000, got=svr.get("worst_case_eur"))

    tok_ev = next(e for e in ev_list if e["agent_name"] == "asset_tokenizer")
    _check("Tokenizer evidence.token_standard present",
           tok_ev["evidence"].get("token_standard") == "ERC-3643 T-REX",
           got=tok_ev["evidence"].get("token_standard"))
    _check("Tokenizer evidence.total_tokens = 2000",
           tok_ev["evidence"].get("total_tokens") == 2000,
           got=tok_ev["evidence"].get("total_tokens"))

    # governance_gate
    gate = pkg["governance_gate"]
    _check("gate_outcome = pass", gate["gate_outcome"] == "pass", got=gate["gate_outcome"])
    _check("mandatory_gates has 5 entries", len(gate["mandatory_gates"]) == 5,
           got=len(gate["mandatory_gates"]))

    # consensus_seal — real ECDSA seal
    seal = pkg["consensus_seal"]
    _check("seal.status = sealed", seal["status"] == "sealed", got=seal["status"])
    _check("seal.canonical_hash starts with sha256:",
           (seal.get("canonical_hash") or "").startswith("sha256:"),
           got=(seal.get("canonical_hash") or "")[:20])
    _check("seal.signature present (hex DER ECDSA)",
           bool(seal.get("signature")), got=(seal.get("signature") or "")[:16] + "...")
    _check("seal.gates_cleared has 5 entries",
           len(seal.get("gates_cleared") or []) == 5,
           got=len(seal.get("gates_cleared") or []))
    _check("seal.curve = SECP256K1", seal.get("curve") == "SECP256K1", got=seal.get("curve"))

    # explainability
    exp = pkg["explainability"]
    _check("explainability.headline non-empty", bool(exp.get("headline")),
           got=(exp.get("headline") or "")[:40])
    _check("explainability.per_agent_summary non-empty",
           len(exp.get("per_agent_summary", [])) > 0,
           got=len(exp.get("per_agent_summary", [])))

    # human_authorization
    _check("human_authorization is None (not yet signed)",
           pkg["human_authorization"] is None, got=pkg["human_authorization"])

    return pkg


# ── PATH B — KYC halt ─────────────────────────────────────────────────────────

def test_kyc_halt() -> dict:
    print()
    print(_SEP)
    print("  PATH B — KYC halt  (REQ-2043, Viktor Petrov, WL-001 PEP match)")
    print("           pipeline_status=halted_kyc; tokenizer skipped; seal blocked.")
    print(_SEP)

    overrides = {
        "doc_auditor":        _mock_doc_pass,
        "kyc_guardian":       _mock_kyc_halt,
        "dynamic_compliance": _mock_compliance_pass,
        "stress_test":        _mock_stress_pass,   # runs in parallel (not blocked in stage 1)
        "asset_tokenizer":    _mock_tokenizer_pass,
    }

    decision_record, event_log = run_pipeline(
        _CLIENT_PETROV,
        _agent_overrides=overrides,
        _synthesis_override=_mock_synthesis,
    )

    pkg = assemble_evidence_package(decision_record, event_log, _CLIENT_PETROV)

    print()
    print("  STRUCTURE ASSERTIONS")

    # All 8 sections still present even on halt
    for section in ("package_metadata", "case_summary", "decision_lineage",
                    "agent_evidence", "governance_gate", "consensus_seal",
                    "explainability", "human_authorization"):
        _check(f"section '{section}' present", section in pkg)

    # pipeline_status reflects halt
    cs = pkg["case_summary"]
    _check("pipeline_status = halted_kyc",
           cs["pipeline_status"] == "halted_kyc", got=cs["pipeline_status"])
    _check("asset_type = Luxury Villa",
           cs["asset_type"] == "Luxury Villa", got=cs["asset_type"])
    _check("final_decision is None", cs["final_decision"] is None)

    # KYC evidence — halt with WL-001 match
    ev_list = pkg["agent_evidence"]
    kyc_ev = next(e for e in ev_list if e["agent_name"] == "kyc_guardian")
    _check("KYC verdict = halt", kyc_ev["verdict"] == "halt", got=kyc_ev["verdict"])
    sr = kyc_ev["evidence"].get("screening_result")
    _check("KYC screening_result present in evidence", sr is not None, got=sr is not None)
    _check("KYC screening matched=True (Viktor WL-001 hit)",
           sr is not None and sr["matched"] is True, got=sr and sr["matched"])
    _check("KYC screening match_type=pep",
           sr is not None and sr["match_type"] == "pep", got=sr and sr["match_type"])
    _check("KYC screening match_score=1.0",
           sr is not None and sr["match_score"] == 1.0, got=sr and sr["match_score"])
    matched_entry = (sr or {}).get("matched_entry") or {}
    _check("KYC matched_entry.id = WL-001",
           matched_entry.get("id") == "WL-001", got=matched_entry.get("id"))
    _check("KYC matched_entry.source = FATF PEP Register",
           matched_entry.get("source") == "FATF PEP Register",
           got=matched_entry.get("source"))

    # Tokenizer absent (skipped on halt)
    ev_names = [e["agent_name"] for e in ev_list]
    _check("asset_tokenizer absent from evidence (pipeline halted before stage 2)",
           "asset_tokenizer" not in ev_names, got=ev_names)

    # governance_gate
    gate = pkg["governance_gate"]
    _check("gate_outcome = halt", gate["gate_outcome"] == "halt", got=gate["gate_outcome"])

    # consensus_seal — blocked (not sealed)
    seal = pkg["consensus_seal"]
    _check("seal.status = blocked", seal["status"] == "blocked", got=seal["status"])
    _check("seal.canonical_hash is None on blocked path",
           seal.get("canonical_hash") is None, got=seal.get("canonical_hash"))

    # lineage contains stage2_skip
    lineage = pkg["decision_lineage"]
    _check("lineage contains stage2_skip event",
           any(e["event"] == "stage2_skip" for e in lineage), got="found")

    # human_authorization
    _check("human_authorization is None", pkg["human_authorization"] is None)

    return pkg


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print(_SEP2)
    print("  BRIGHTUITY — Governance & Audit Agent — Test Suite")
    print("  Assembles Evidence Package from mocked pipelines. No real LLM calls.")
    print("  ConsensusSigner is REAL (ECDSA) on Path A.")
    print(_SEP2)

    pkg_a = test_happy_path()
    pkg_b = test_kyc_halt()

    # ── Summary ────────────────────────────────────────────────────────────────
    n_checks = len(_checks)
    n_fail   = len(_failures)
    n_pass   = n_checks - n_fail

    print()
    print(_SEP2)
    if not _failures:
        print(f"  [{_OK}]  All {n_checks} assertions passed.")
    else:
        print(f"  {n_pass}/{n_checks} assertions passed. {n_fail} FAILED:")
        for f in _failures:
            print(f"    [{_FAIL}]  {f}")
    print(_SEP2)

    # ── Pretty print happy-path package ───────────────────────────────────────
    print()
    print(_SEP2)
    print("  EVIDENCE PACKAGE (PATH A — HAPPY PATH)  —  pretty JSON sample")
    print(_SEP2)

    # Truncate long fields for readability
    def _truncate(obj: object, max_str: int = 120) -> object:
        if isinstance(obj, str) and len(obj) > max_str:
            return obj[:max_str] + f"...({len(obj)} chars)"
        if isinstance(obj, dict):
            return {k: _truncate(v, max_str) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_truncate(v, max_str) for v in obj]
        return obj

    print(json.dumps(_truncate(pkg_a, max_str=100), indent=2, ensure_ascii=False))

    print()
    sys.exit(1 if _failures else 0)
