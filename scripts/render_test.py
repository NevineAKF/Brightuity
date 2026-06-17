"""
scripts/render_test.py
Brightuity -- PDF renderer smoke test. Laptop venv only; no server required.

Behaviour:
    1. For each of REQ-2041 and REQ-2043: fetch from the case store.
       If not present -> print "not in store" and skip.
       If present -> render to ./tmp/EVP-{id}-{pipeline_status}.pdf.

    2. For REQ-2041 (if present): also render a mock-signed version
       to ./tmp/EVP-REQ-2041-SIGNED.pdf with a fabricated human_authorization
       dict to prove the signed-state layout.

    3. Always render a SYNTHETIC layout test using a fully fabricated package
       (request_id="SYNTHETIC-LAYOUT-TEST") to ./tmp/ -- this exercises every
       rendering code path regardless of DB state.

Usage:
    python scripts/render_test.py
    (run from the project root or any directory)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Bootstrap PYTHONPATH so project imports work from any CWD ─────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point case_store at the default DB (override via CASES_DB_PATH env if needed)
os.environ.setdefault(
    "CASES_DB_PATH",
    str(ROOT / "database" / "brightuity_cases.db"),
)

from backend.case_store import get_evidence_package          # noqa: E402
from backend.pdf_renderer import write_evidence_package_pdf  # noqa: E402

OUTPUT_DIR = ROOT / "tmp"
_REAL_CASES = ["REQ-2041", "REQ-2043"]


# ── Page-count helper ─────────────────────────────────────────────────────────

def _count_pages(path: str) -> int:
    """
    Count pages in a ReportLab-generated PDF by scanning for /Type /Page markers.
    Returns -1 if the file cannot be read or no markers are found.
    """
    try:
        data = Path(path).read_bytes()
        # ReportLab emits "/Type /Page\n" (or with tab/space) for each page object
        return len(re.findall(rb"/Type\s*/Page\b", data))
    except OSError:
        return -1


# ── Synthetic evidence package ────────────────────────────────────────────────

def _build_synthetic_package() -> dict[str, Any]:
    """
    Build a fully fabricated evidence package for renderer layout testing.

    This is NOT a real case and NOT fetched from the store.  It exercises
    every section, evidence field, and rendering code path.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ts  = now.replace("-", "").replace(":", "").replace("+00:00", "Z")

    # Realistic-looking but entirely fake cryptographic values
    fake_hash = "sha256:" + "a3f91c2e4b8d7e6f" * 4  # 64 hex chars after prefix
    fake_sig  = "3046022100" + "d8e4f6a1c3b7a92d" * 8 + "022100" + "e1f3a7b2" * 8
    fake_pk   = "02" + "b4c7d9e1f2a3c5d6" * 4

    return {
        "package_metadata": {
            "package_id":      f"EVP-SYNTHETIC-LAYOUT-TEST-{ts}",
            "generated_at":    now,
            "institution":     "Meridian Digital Bank -- Digital Assets & Tokenization Division",
            "classification":  "Confidential -- Internal Decision Record",
            "schema_version":  "1.0",
        },
        "case_summary": {
            "request_id":      "SYNTHETIC-LAYOUT-TEST",
            "client_id":       "CLT-9999",
            "asset_type":      "Commercial Real Estate",
            "asset_detail":    "Grade A office building, Frankfurt CBD -- approx. 2,400 m²",
            "asset_value_eur": 2_500_000.0,
            "jurisdiction":    "Germany (MiCA / BaFin)",
            "pipeline_status": "approved_pending_human",
            "final_decision":  None,
        },
        "decision_lineage": [
            {
                "step": 1, "event": "pipeline_start",
                "agent": None, "timestamp_ms": 0,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 2, "event": "stage1_start",
                "agent": None, "timestamp_ms": 50,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 3, "event": "agent_complete",
                "agent": "doc_auditor", "timestamp_ms": 3200,
                "model_used": "google/gemini-3-5-flash",
                "was_fallback": False, "latency_ms": 3150,
            },
            {
                "step": 4, "event": "agent_complete",
                "agent": "kyc_guardian", "timestamp_ms": 5800,
                "model_used": "claude-opus-4-8",
                "was_fallback": False, "latency_ms": 5750,
            },
            {
                "step": 5, "event": "agent_complete",
                "agent": "dynamic_compliance", "timestamp_ms": 24100,
                "model_used": "google/gemini-2.5-pro",
                "was_fallback": False, "latency_ms": 18300,
            },
            {
                "step": 6, "event": "agent_complete",
                "agent": "stress_test", "timestamp_ms": 8900,
                "model_used": "google/gemini-3-5-flash",
                "was_fallback": False, "latency_ms": 8850,
            },
            {
                "step": 7, "event": "stage1_complete",
                "agent": None, "timestamp_ms": 24100,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 8, "event": "gate_result",
                "agent": None, "timestamp_ms": 24150,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 9, "event": "stage2_start",
                "agent": "asset_tokenizer", "timestamp_ms": 24200,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 10, "event": "agent_complete",
                "agent": "asset_tokenizer", "timestamp_ms": 31400,
                "model_used": "gpt-4o",
                "was_fallback": False, "latency_ms": 7200,
            },
            {
                "step": 11, "event": "stage3_start",
                "agent": "consensus_signer", "timestamp_ms": 31500,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 12, "event": "seal_complete",
                "agent": "consensus_signer", "timestamp_ms": 31610,
                "model_used": None, "was_fallback": None, "latency_ms": 110,
            },
            {
                "step": 13, "event": "pipeline_complete",
                "agent": None, "timestamp_ms": 31650,
                "model_used": None, "was_fallback": None, "latency_ms": None,
            },
            {
                "step": 14, "event": "briefing_complete",
                "agent": "orchestrator", "timestamp_ms": 38900,
                "model_used": "claude-opus-4-8",
                "was_fallback": False, "latency_ms": 7250,
            },
        ],
        "agent_evidence": [
            {
                "agent_name":   "doc_auditor",
                "role":         "Document Auditor",
                "verdict":      "pass",
                "summary":      (
                    "All required documentation present and complete. "
                    "Land registry extract dated within 90 days. "
                    "Independent CBRE valuation confirms €2.5M market value. "
                    "Corporate deed verified; no encumbrances detected. "
                    "Ownership chain unbroken across three prior transfers."
                ),
                "model_used":   "google/gemini-3-5-flash",
                "was_fallback": False,
                "latency_ms":   3150,
                "evidence": {
                    "issues_found": [],
                },
            },
            {
                "agent_name":   "kyc_guardian",
                "role":         "KYC & AML Compliance Officer",
                "verdict":      "pass",
                "summary":      (
                    "Identity verified against EU-issued passport (DE). "
                    "No matches across OFAC, EU consolidated, and UK HM Treasury lists. "
                    "No PEP designation confirmed via World-Check and Refinitiv Orbis. "
                    "Source of funds: proceeds from verified sale of software business "
                    "(Companies House reference CRN-88124-DE on file). "
                    "Risk classification: Standard."
                ),
                "model_used":   "claude-opus-4-8",
                "was_fallback": False,
                "latency_ms":   5750,
                "evidence": {
                    "flags_raised": [],
                    "screening_result": {
                        "ofac_match":     False,
                        "eu_list_match":  False,
                        "uk_list_match":  False,
                        "pep_designation": False,
                        "risk_tier":      "Standard",
                        "world_check_id": "WC-20260617-0482",
                    },
                },
            },
            {
                "agent_name":   "dynamic_compliance",
                "role":         "Regulatory Compliance Analyst",
                "verdict":      "pass",
                "summary":      (
                    "Asset tokenization permissible under MiCA Title III. "
                    "German BaFin notification threshold not exceeded (sub-€5M). "
                    "ERC-3643 T-REX framework with enforced transfer restrictions "
                    "is compliant with MiCA Art. 19 (issuance requirements) and "
                    "Art. 22 (ongoing obligations). AMLD5 beneficial ownership "
                    "transparency satisfied."
                ),
                "model_used":   "google/gemini-2.5-pro",
                "was_fallback": False,
                "latency_ms":   18300,
                "evidence": {
                    "jurisdiction": "Germany (MiCA / BaFin)",
                    "citations": [
                        "MiCA Regulation (EU) 2023/1114 -- Art. 19: Asset-referenced token issuance",
                        "MiCA Art. 22: Ongoing obligations for significant ART issuers",
                        "AMLD5 Art. 30: Beneficial ownership transparency",
                        "BaFin Circular 10/2023: Digital assets classification guidance",
                        "EBA Guidelines EBA/GL/2022/16: AML/CFT for crypto-asset transfers",
                    ],
                    "concerns": [],
                    "retrieved_k": 12,
                },
            },
            {
                "agent_name":   "stress_test",
                "role":         "Market & Liquidity Risk Analyst",
                "verdict":      "pass",
                "summary":      (
                    "Risk score 28/100 (LOW). Asset is Grade A commercial real estate "
                    "in stable Frankfurt CBD location with 96.4% occupancy. "
                    "Five stress scenarios tested: property correction (–30%), "
                    "rate shock (+200 bp), liquidity squeeze, vacancy spike, FX shock. "
                    "Portfolio loss contained within acceptable thresholds across all scenarios. "
                    "Minimum stressed value: €1.72M (31.2% haircut)."
                ),
                "model_used":   "google/gemini-3-5-flash",
                "was_fallback": False,
                "latency_ms":   8850,
                "evidence": {
                    "risk_level":   "low",
                    "risk_factors": [
                        "Current occupancy 96.4% (anchor tenants on 5-year leases)",
                        "Loan-to-value ratio 42% -- conservative leverage",
                        "Frankfurt office vacancy rate 7.2% (5-year low)",
                        "No floating-rate debt exposure on this asset",
                    ],
                    "risk_metrics": {
                        "risk_score":            28,
                        "ltv_ratio":             0.42,
                        "occupancy_pct":         96.4,
                        "stressed_value_min_eur": 1_720_000,
                        "stressed_value_max_eur": 2_480_000,
                        "worst_case_loss_pct":    31.2,
                    },
                },
            },
            {
                "agent_name":   "asset_tokenizer",
                "role":         "Digital Asset Structuring Specialist",
                "verdict":      "pass",
                "summary":      (
                    "Proposed ERC-3643 T-REX token structure: 2,500,000 tokens at €1.00 each. "
                    "Transfer restricted to KYC-verified wallets on Meridian permissioned registry. "
                    "12-month lock-up period post primary issuance. "
                    "Quarterly redemption windows with 90-day notice period."
                ),
                "model_used":   "gpt-4o",
                "was_fallback": False,
                "latency_ms":   7200,
                "evidence": {
                    "token_standard":      "ERC-3643 T-REX (Transfer Restrictions for RWA)",
                    "total_tokens":        2_500_000,
                    "value_per_token_eur": 1.0,
                    "structure_notes": [
                        "Transfer restricted to KYC-verified wallets on Meridian permissioned registry",
                        "12-month lock-up post primary issuance",
                        "Quarterly redemption windows -- 90-day notice required",
                        "Governance: 67% supermajority required for structural changes",
                        "Custodian: Meridian Digital Custody GmbH (BaFin-licensed)",
                    ],
                },
            },
        ],
        "governance_gate": {
            "mandatory_gates": [
                "doc_auditor",
                "kyc_guardian",
                "dynamic_compliance",
            ],
            "gate_outcome": "pass",
            "gate_reason":  (
                "All mandatory gates cleared (Doc ✓ KYC ✓ Compliance ✓). "
                "Stress-test=pass (advisory gate also cleared)."
            ),
            "advisory_notes": [],
        },
        "consensus_seal": {
            "status":         "sealed",
            "canonical_hash": fake_hash,
            "signature":      fake_sig,
            "public_key":     fake_pk,
            "curve":          "SECP256K1",
            "sealed_at":      now,
            "gates_cleared": [
                "doc_auditor",
                "kyc_guardian",
                "dynamic_compliance",
                "stress_test",
                "asset_tokenizer",
            ],
            "failed_gate": None,
        },
        "explainability": {
            "headline": (
                "APPROVED -- All five specialist gates cleared; ECDSA seal produced. "
                "Pending Head of Digital Assets authorization."
            ),
            "decisive_factor": (
                "Clean KYC verification with no PEP or sanctions flags across "
                "OFAC, EU consolidated, and UK HM Treasury lists."
            ),
            "per_agent_summary": [
                "Doc Auditor: PASS -- Complete documentation package; CBRE valuation confirmed €2.5M.",
                "KYC Guardian: PASS -- Identity verified; zero sanctions/PEP matches; Standard risk tier.",
                "Dynamic Compliance: PASS -- MiCA Art. 19/22 compliant; BaFin notification not required.",
                "Stress-Test: PASS -- Risk score 28/100 (LOW); stressed floor €1.72M.",
                "Asset Tokenizer: PASS -- ERC-3643 T-REX; 2.5M tokens at €1.00 each.",
            ],
            "recommendation": (
                "System recommends APPROVAL. All mandatory compliance gates have cleared. "
                "Risk profile is low. Token structure is MiCA-compliant with appropriate "
                "transfer restrictions and custodian controls. "
                "Final approval authority rests with the Head of Digital Assets -- "
                "no automated system may authorize on behalf of the human reviewer."
            ),
        },
        "human_authorization": None,
    }


# ── Mock signed package builder ───────────────────────────────────────────────

def _add_mock_auth(base_pkg: dict[str, Any]) -> dict[str, Any]:
    """
    Return a deep copy of base_pkg with a mock human_authorization dict injected.
    Used only to test the signed-state rendering path.
    """
    pkg = json.loads(json.dumps(base_pkg, default=str))   # deep copy
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pkg["human_authorization"] = {
        "decision": "approved",
        "rationale": (
            "Having reviewed the complete evidence package including all five specialist "
            "verdicts and the ECDSA-sealed audit trail, I am satisfied that the mandatory "
            "compliance gates have been correctly evaluated. Documentation is complete, "
            "KYC verification is clean, regulatory compliance is confirmed under MiCA, "
            "and the risk profile is within our policy limits. I authorize tokenization "
            "to proceed under the proposed ERC-3643 T-REX structure."
        ),
        "signatory_name":          "Nevine Fakhreddin",
        "signatory_role":          "Head of Digital Assets",
        "signed_at":               now,
        "authorization_hash":      "DEMO-PLACEHOLDER",
        "authorization_signature": "DEMO-PLACEHOLDER",
    }
    # Also update case_summary.final_decision so the cover page shows APPROVED
    if "case_summary" in pkg:
        pkg["case_summary"]["final_decision"] = "approved"

    return pkg


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced: list[tuple[str, int]] = []   # (path, page_count)

    print("=" * 70)
    print("Brightuity -- PDF Renderer Test")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 70)

    # ── 1. Real cases from the store ──────────────────────────────────────────
    print("\n[Real cases]")
    for req_id in _REAL_CASES:
        pkg = get_evidence_package(req_id)
        if pkg is None:
            print(f"  {req_id}: not in store - skipping.")
            continue

        pipeline_status = (
            (pkg.get("case_summary") or {}).get("pipeline_status", "unknown")
            or "unknown"
        )
        out_path = str(OUTPUT_DIR / f"EVP-{req_id}-{pipeline_status}.pdf")
        written  = write_evidence_package_pdf(pkg, out_path)
        pages    = _count_pages(written)
        print(f"  {req_id}: rendered -> {written}  ({pages} pages)")
        produced.append((written, pages))

        # Mock-signed copy for REQ-2041 only
        if req_id == "REQ-2041":
            pkg_signed   = _add_mock_auth(pkg)
            out_signed   = str(OUTPUT_DIR / "EVP-REQ-2041-SIGNED.pdf")
            written_sig  = write_evidence_package_pdf(pkg_signed, out_signed)
            pages_sig    = _count_pages(written_sig)
            print(f"  {req_id} (MOCK SIGNED): rendered -> {written_sig}  ({pages_sig} pages)")
            produced.append((written_sig, pages_sig))

    # ── 2. Synthetic layout test (always runs) ────────────────────────────────
    print("\n[Synthetic layout test -- exercises all rendering code paths]")

    synthetic_pkg = _build_synthetic_package()

    # 2a. Unsigned (pending authorization)
    out_unsgn = str(OUTPUT_DIR / "EVP-SYNTHETIC-UNSIGNED.pdf")
    w_unsgn   = write_evidence_package_pdf(synthetic_pkg, out_unsgn)
    p_unsgn   = _count_pages(w_unsgn)
    print(f"  SYNTHETIC (unsigned): rendered -> {w_unsgn}  ({p_unsgn} pages)")
    produced.append((w_unsgn, p_unsgn))

    # 2b. Signed (mock human authorization)
    synthetic_signed = _add_mock_auth(synthetic_pkg)
    out_sgn   = str(OUTPUT_DIR / "EVP-SYNTHETIC-SIGNED.pdf")
    w_sgn     = write_evidence_package_pdf(synthetic_signed, out_sgn)
    p_sgn     = _count_pages(w_sgn)
    print(f"  SYNTHETIC (signed):   rendered -> {w_sgn}  ({p_sgn} pages)")
    produced.append((w_sgn, p_sgn))

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"Done. {len(produced)} PDF(s) produced:\n")
    for path, pages in produced:
        print(f"  {pages:3d} pages  {path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
