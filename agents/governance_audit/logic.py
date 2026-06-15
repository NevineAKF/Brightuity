"""
agents/governance_audit/logic.py
Brightuity — Governance & Audit Agent (Agent 8).

Assembles the complete Decision Evidence Package from a finished pipeline run.
Pure deterministic Python — no LLM, no network, no new decisions.

The assembler collects what every prior agent produced and structures it into
one auditable EvidencePackage. It is the downstream consumer of all agent
outputs and is the last deterministic step before the document goes to the
human reviewer.

What this module DOES:
  - Maps decision_record + event_log into the EvidencePackage schema.
  - Generates a unique package_id and captured-at timestamp.
  - Attaches agent-specific provenance fields (KYC screening_result watchlist
    match, Stress-Test risk_metrics with computed formula, doc issues_found,
    compliance citations, tokenizer structure).
  - Validates the assembled package against the EvidencePackage Pydantic model.

What this module DOES NOT DO:
  - No LLM calls, no new verdicts, no gate changes.
  - No modification of any agent result.
  - No PII — same boundary as the Consensus Signer: name, passport, DOB, address
    are NOT included in the evidence package; they remain in DB1.

Public interface:
    assemble_evidence_package(
        decision_record: dict,
        event_log: list[dict],
        client_record: dict | None = None,
    ) -> dict
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.schemas import (
    AgentEvidenceEntry,
    CaseSummary,
    ConsensusSealRecord,
    DecisionLineageEntry,
    EvidencePackage,
    ExplainabilityRecord,
    GovernanceGateRecord,
    PackageMetadata,
)

# ── Agent role labels for the audit report ─────────────────────────────────────
_AGENT_ROLES: dict[str, str] = {
    "doc_auditor":        "Document Auditor",
    "kyc_guardian":       "KYC & AML Compliance Officer",
    "dynamic_compliance": "Regulatory Compliance Analyst",
    "stress_test":        "Market & Liquidity Risk Analyst",
    "asset_tokenizer":    "Digital Asset Structuring Specialist",
}

# Pipeline-ordered list of Stage 1 + Stage 2 agents
_AGENT_ORDER: tuple[str, ...] = (
    "doc_auditor",
    "kyc_guardian",
    "dynamic_compliance",
    "stress_test",
    "asset_tokenizer",
)


# ── Evidence extraction helpers ────────────────────────────────────────────────

def _extract_agent_evidence(agent_name: str, result: dict) -> dict[str, Any]:
    """
    Extract the agent-specific evidence fields from a verdict dict.

    These are the fields beyond the common (verdict, summary, model_used,
    was_fallback, latency_ms) that provide the substantive audit trail:
    issues, watchlist matches, regulatory citations, risk metrics, etc.
    """
    if agent_name == "doc_auditor":
        return {
            "issues_found": result.get("issues_found", []),
        }

    if agent_name == "kyc_guardian":
        return {
            "flags_raised":     result.get("flags_raised", []),
            "screening_result": result.get("screening_result"),
        }

    if agent_name == "dynamic_compliance":
        return {
            "jurisdiction": result.get("jurisdiction"),
            "citations":    result.get("citations", []),
            "concerns":     result.get("concerns", []),
            "retrieved_k":  result.get("retrieved_k"),
        }

    if agent_name == "stress_test":
        return {
            "risk_level":   result.get("risk_level"),
            "risk_factors": result.get("risk_factors", []),
            "risk_metrics": result.get("risk_metrics"),
        }

    if agent_name == "asset_tokenizer":
        return {
            "token_standard":      result.get("token_standard"),
            "total_tokens":        result.get("total_tokens"),
            "value_per_token_eur": result.get("value_per_token_eur"),
            "structure_notes":     result.get("structure_notes", []),
        }

    # Unknown agent — preserve all non-standard fields as-is
    standard_keys = {"agent", "verdict", "summary", "model_used", "was_fallback", "latency_ms"}
    return {k: v for k, v in result.items() if k not in standard_keys}


def _build_advisory_notes(agents: dict[str, dict | None]) -> list[str]:
    """Generate advisory notes for the governance gate section."""
    notes: list[str] = []
    stress = agents.get("stress_test")
    if stress and stress.get("verdict") not in ("pass", None, ""):
        rm = stress.get("risk_metrics") or {}
        score = rm.get("risk_score", "")
        level = stress.get("risk_level", stress.get("verdict", ""))
        notes.append(
            f"Stress-Test returned '{stress['verdict']}' (risk_level={level}"
            + (f", risk_score={score}/100" if score != "" else "")
            + "). Advisory non-block at orchestrator level; "
            "Consensus Signer enforces this gate independently."
        )
    tok = agents.get("asset_tokenizer")
    if tok and "exception" in tok:
        notes.append("Asset Tokenizer raised an exception — safe default applied.")
    return notes


# ── Public interface ───────────────────────────────────────────────────────────

def assemble_evidence_package(
    decision_record: dict,
    event_log: list[dict],
    client_record: dict | None = None,
) -> dict:
    """
    Assemble a complete, Pydantic-validated Decision Evidence Package.

    Args:
        decision_record:  The dict returned as the first element of run_pipeline().
        event_log:        The list returned as the second element of run_pipeline().
        client_record:    Optional original client dict. When provided, case_summary
                          is enriched with asset_detail and client_id. When absent,
                          values are extracted from the seal's canonical_record (if
                          available) or left None.

    Returns:
        Validated EvidencePackage serialised as a plain dict (model_dump()).
    """
    request_id  = decision_record.get("request_id", "UNKNOWN")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # package_id: EVP-<request_id>-<YYYYMMDDTHHmmss> — unique, sortable, readable
    ts_compact = generated_at.replace("-", "").replace(":", "").replace("+00:00", "Z")
    package_id = f"EVP-{request_id}-{ts_compact}"

    agents: dict[str, dict | None] = decision_record.get("agents", {})
    seal_raw:  dict = decision_record.get("seal") or {}
    briefing:  dict = decision_record.get("briefing") or {}

    # ── case_summary ──────────────────────────────────────────────────────────
    # Non-PII fields only. Try client_record first, then seal canonical_record.
    canonical = seal_raw.get("canonical_record") or {}

    cr = client_record or {}
    client_id    = cr.get("client_id")    or canonical.get("client_id")
    asset_type   = cr.get("asset_type")   or canonical.get("asset_type")
    asset_detail = cr.get("asset_detail")
    asset_value  = cr.get("asset_value_eur") or canonical.get("asset_value_eur")

    # Jurisdiction from compliance agent if available
    comp = agents.get("dynamic_compliance") or {}
    jurisdiction = comp.get("jurisdiction") or None

    case_summary = CaseSummary(
        request_id=request_id,
        client_id=client_id,
        asset_type=asset_type,
        asset_detail=asset_detail,
        asset_value_eur=float(asset_value) if asset_value is not None else None,
        jurisdiction=jurisdiction,
        pipeline_status=decision_record.get("pipeline_status", "unknown"),
        final_decision=None,
    )

    # ── decision_lineage — ordered from event_log ─────────────────────────────
    lineage: list[DecisionLineageEntry] = []
    for step, ev in enumerate(event_log, start=1):
        lineage.append(DecisionLineageEntry(
            step=step,
            event=ev.get("event", ""),
            agent=ev.get("agent"),
            timestamp_ms=ev.get("timestamp_ms", 0),
            model_used=ev.get("model_used"),
            was_fallback=ev.get("was_fallback"),
            latency_ms=ev.get("latency_ms"),
        ))

    # ── agent_evidence — one entry per agent that ran ─────────────────────────
    agent_evidence: list[AgentEvidenceEntry] = []
    for name in _AGENT_ORDER:
        result = agents.get(name)
        if result is None:
            continue
        agent_evidence.append(AgentEvidenceEntry(
            agent_name=name,
            role=_AGENT_ROLES.get(name, name),
            verdict=result.get("verdict", "unknown"),
            summary=result.get("summary", ""),
            model_used=result.get("model_used", "none"),
            was_fallback=bool(result.get("was_fallback", False)),
            latency_ms=int(result.get("latency_ms", 0)),
            evidence=_extract_agent_evidence(name, result),
        ))

    # ── governance_gate ───────────────────────────────────────────────────────
    from agents.consensus_signer.logic import MANDATORY_GATES
    gate = GovernanceGateRecord(
        mandatory_gates=list(MANDATORY_GATES),
        gate_outcome=decision_record.get("gate_outcome", "unknown"),
        gate_reason=decision_record.get("gate_reason", ""),
        advisory_notes=_build_advisory_notes(agents),
    )

    # ── consensus_seal ────────────────────────────────────────────────────────
    consensus_seal = ConsensusSealRecord(
        status=seal_raw.get("status", "unknown"),
        canonical_hash=seal_raw.get("canonical_hash"),
        signature=seal_raw.get("signature"),
        public_key=seal_raw.get("public_key"),
        curve=seal_raw.get("curve"),
        sealed_at=seal_raw.get("sealed_at"),
        gates_cleared=seal_raw.get("gates_cleared"),
        failed_gate=seal_raw.get("failed_gate"),
    )

    # ── explainability ────────────────────────────────────────────────────────
    explainability = ExplainabilityRecord(
        headline=briefing.get("headline", "(briefing unavailable)"),
        decisive_factor=briefing.get("decisive_factor", ""),
        per_agent_summary=briefing.get("per_agent_summary", []),
        recommendation=briefing.get("recommendation", ""),
    )

    # ── Assemble and validate ─────────────────────────────────────────────────
    package = EvidencePackage(
        package_metadata=PackageMetadata(
            package_id=package_id,
            generated_at=generated_at,
            institution="Meridian Digital Bank — Digital Assets & Tokenization Division",
            classification="Confidential — Internal Decision Record",
            schema_version="1.0",
        ),
        case_summary=case_summary,
        decision_lineage=lineage,
        agent_evidence=agent_evidence,
        governance_gate=gate,
        consensus_seal=consensus_seal,
        explainability=explainability,
        human_authorization=None,
    )

    return package.model_dump()
