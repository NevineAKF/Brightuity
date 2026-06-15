"""
shared/schemas.py
Brightuity — Pydantic verdict schemas for every LLM agent.

These are the single source of truth for what each agent MUST return.
They serve two purposes simultaneously:
  1. Request-time: model_json_schema() is sent to the API in json_schema mode
     so the platform enforces the structure before we even see the response.
  2. Response-time: model_validate() validates every response before it is
     accepted as a verdict — malformed output routes to failover, not through.

Adding a new agent: add its schema here, import it in the agent's logic.py,
pass it to call_agent_model(). Nothing else in the engine needs to change.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class DocAuditorVerdict(BaseModel):
    """
    Output contract for the Doc Auditor agent.
    First compliance gate — document completeness and ownership-chain integrity.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    issues_found: list[str]


class KycGuardianVerdict(BaseModel):
    """
    Output contract for the KYC Guardian agent.
    Three-verdict system: halt is a hard pipeline stop requiring human sign-off.
    """
    verdict:      Literal["pass", "fail", "halt"]
    summary:      str
    flags_raised: list[str]


class DynamicComplianceVerdict(BaseModel):
    """
    Output contract for the Dynamic Compliance agent.
    RAG-grounded regulatory opinion — citations prove grounding in retrieved law.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    jurisdiction: str
    citations:    list[str]
    concerns:     list[str]


class StressTestVerdict(BaseModel):
    """
    Output contract for the Stress-Test Simulator agent.
    Quantitative market and liquidity risk assessment for RWA tokenisation.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    risk_level:   Literal["low", "medium", "high", "critical"]
    risk_factors: list[str]


class StressTestNarrative(BaseModel):
    """
    LLM-only output contract for the Stress-Test Simulator.

    The deterministic risk engine (risk_engine.py) computes risk_score,
    risk_level, stressed_value_range, and verdict. The LLM produces only
    the interpretive narrative: summary and enriched risk_factors.
    verdict and risk_level are NOT produced by the LLM — they are
    overridden with engine values in logic.py.
    """
    summary:      str
    risk_factors: list[str]


class AssetTokenizerVerdict(BaseModel):
    """
    Output contract for the Asset Tokenizer agent.
    Proposes the on-chain tokenisation structure for a real-world asset.
    Does not mint or issue — it produces a structure recommendation for human approval.
    """
    verdict:             Literal["pass", "fail"]
    summary:             str
    token_standard:      str     # proposed standard / class label (e.g. ERC-3643 T-REX)
    total_tokens:        int     # proposed total supply
    value_per_token_eur: float   # nominal EUR value per token
    structure_notes:     list[str]  # key parameters, assumptions, caveats


class OrchestratorBriefing(BaseModel):
    """
    Output contract for the Orchestrator Layer 2 synthesis (Claude Opus 4.8).

    Produced AFTER the deterministic Layer 1 (gates + ECDSA seal) has fully
    completed. The briefing describes what Layer 1 decided — it has zero
    authority to change or contradict those decisions.

    Drives both:
      1. Request-time: json_schema strict sent to AI/ML API so Claude is
         constrained to this exact structure before we see the response.
      2. Response-time: model_validate() ensures the response conforms before
         it is attached to decision_record["briefing"].
    """
    headline:          str        # one line: outcome statement (e.g. "HALTED — KYC PEP match")
    decisive_factor:   str        # the single most important reason for the outcome
    per_agent_summary: list[str]  # one concise line per specialist agent that ran
    recommendation:    str        # advised action for the Head of Digital Assets;
                                  # must explicitly leave final approve/reject to the human


# ── Governance & Audit Evidence Package ───────────────────────────────────────
# Assembled by agents/governance_audit/logic.py after a pipeline run completes.
# Pure structure — no LLM, no decisions. Maps decision_record + event_log into
# a single auditable object ready for human review and eventual e-signature.

class PackageMetadata(BaseModel):
    """Provenance and classification metadata for the evidence package."""
    package_id:       str   # "EVP-<request_id>-<UTC timestamp>"
    generated_at:     str   # ISO 8601 UTC
    institution:      str
    classification:   str
    schema_version:   str


class CaseSummary(BaseModel):
    """Non-PII case identity and outcome for the header section."""
    request_id:       str
    client_id:        Optional[str]   = None
    asset_type:       Optional[str]   = None
    asset_detail:     Optional[str]   = None
    asset_value_eur:  Optional[float] = None
    jurisdiction:     Optional[str]   = None
    pipeline_status:  str
    final_decision:   Optional[str]   = None   # null until human signs


class DecisionLineageEntry(BaseModel):
    """One event from the orchestrator event_log, normalised for the audit trail."""
    step:         int
    event:        str
    agent:        Optional[str] = None
    timestamp_ms: int
    model_used:   Optional[str]  = None
    was_fallback: Optional[bool] = None
    latency_ms:   Optional[int]  = None


class AgentEvidenceEntry(BaseModel):
    """Complete evidence record for one agent that participated in the pipeline."""
    agent_name:   str
    role:         str               # human-readable job title for the audit report
    verdict:      str
    summary:      str
    model_used:   str
    was_fallback: bool
    latency_ms:   int
    evidence:     dict[str, Any]    # agent-specific fields (issues, flags, metrics, …)


class GovernanceGateRecord(BaseModel):
    """Gate enforcement summary — which gates were required and what happened."""
    mandatory_gates: list[str]
    gate_outcome:    str            # "pass" | "blocked" | "halt"
    gate_reason:     str
    advisory_notes:  list[str]


class ConsensusSealRecord(BaseModel):
    """The ECDSA tamper-evident seal produced by the Consensus Signer."""
    status:         str                    # "sealed" | "blocked"
    canonical_hash: Optional[str] = None  # "sha256:<hex>" — present when sealed
    signature:      Optional[str] = None  # hex DER ECDSA — present when sealed
    public_key:     Optional[str] = None  # hex compressed EC point — present when sealed
    curve:          Optional[str] = None
    sealed_at:      Optional[str] = None
    gates_cleared:  Optional[list[str]] = None
    failed_gate:    Optional[str] = None  # present when blocked


class ExplainabilityRecord(BaseModel):
    """Human-readable briefing produced by the Layer 2 synthesis (Opus 4.8)."""
    headline:           str
    decisive_factor:    str
    per_agent_summary:  list[str]
    recommendation:     str


class EvidencePackage(BaseModel):
    """
    Complete Decision Evidence Package — the system's primary output.

    Assembled deterministically by the Governance & Audit agent after a pipeline
    run completes. Contains every input, intermediate result, gate decision, ECDSA
    seal, and human-readable briefing in one auditable structure.

    human_authorization starts as None and is populated at e-signature time
    when the Head of Digital Assets signs the final approve/reject decision.
    """
    package_metadata:     PackageMetadata
    case_summary:         CaseSummary
    decision_lineage:     list[DecisionLineageEntry]
    agent_evidence:       list[AgentEvidenceEntry]
    governance_gate:      GovernanceGateRecord
    consensus_seal:       ConsensusSealRecord
    explainability:       ExplainabilityRecord
    human_authorization:  Optional[dict[str, Any]] = None
