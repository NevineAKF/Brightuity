"""
agents/orchestrator/synthesis.py
Brightuity — Orchestrator Layer 2: LLM synthesis.

Runs STRICTLY AFTER the deterministic Layer 1 (gates + ECDSA seal) has
produced and returned its complete decision_record. Reads from that record;
never influences it.

Authority: NONE. This layer describes what Layer 1 decided. It cannot change
pipeline_status, gate_outcome, seal status, or any agent verdict. Those are
sealed and cryptographically committed before this function is ever called.

Failover design:
  Primary  : Claude Opus 4.8  (AI/ML API, json_schema strict)
  Fallback : Claude Sonnet 4.6 (AI/ML API, json_schema strict)
  Both fail: deterministic templated briefing built directly from decision_record.
             The pipeline always completes — an LLM synthesis outage has zero
             impact on the governance decision that is already sealed.

Public interface:
    synthesize_briefing(decision_record: dict) -> dict
    Always returns a dict. Never raises.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import OrchestratorBriefing

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "synthesis_prompt.txt"
).read_text(encoding="utf-8")

# ── Agent display labels (pipeline order) ─────────────────────────────────────
_AGENT_LABELS: tuple[tuple[str, str], ...] = (
    ("doc_auditor",        "Doc Auditor"),
    ("kyc_guardian",       "KYC Guardian"),
    ("dynamic_compliance", "Dynamic Compliance"),
    ("stress_test",        "Stress-Test Simulator"),
    ("asset_tokenizer",    "Asset Tokenizer"),
)


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_synthesis_prompt(decision_record: dict) -> str:
    """
    Build the user-turn prompt from the completed, sealed decision_record.

    Includes: pipeline_status, gate_outcome, gate_reason, request_id,
    asset_type, asset_value_eur (same fields as the canonical record —
    non-PII), each agent's verdict + summary + agent-specific structured
    fields, and seal status.

    Raw PII (full_name, passport_number, date_of_birth, address) is
    never included — the agent summaries describe outcomes in plain
    language without re-exposing personal data.
    """
    status    = decision_record.get("pipeline_status", "unknown")
    gate      = decision_record.get("gate_outcome", "unknown")
    reason    = decision_record.get("gate_reason", "")
    req_id    = decision_record.get("request_id", "UNKNOWN")
    agents    = decision_record.get("agents", {})
    seal      = decision_record.get("seal") or {}

    # Non-PII case metadata from the canonical record
    asset_type  = decision_record.get("asset_type", "")
    asset_value = decision_record.get("asset_value_eur", "")

    lines: list[str] = [
        "COMPLETED PIPELINE DECISION RECORD",
        "=" * 50,
        "",
        f"Request ID     : {req_id}",
        f"Asset Type     : {asset_type}" if asset_type else "",
        f"Asset Value    : EUR {asset_value:,}" if isinstance(asset_value, (int, float)) and asset_value else "",
        "",
        f"Pipeline Status: {status.upper().replace('_', ' ')}",
        f"Gate Outcome   : {gate}",
        f"Gate Reason    : {reason}",
        "",
        "AGENT VERDICTS",
        "-" * 40,
    ]
    # Strip empty lines (e.g. when asset_type is absent)
    lines = [ln for ln in lines if ln != ""]

    for key, label in _AGENT_LABELS:
        result = agents.get(key)
        if result is None:
            continue

        verdict  = result.get("verdict", "unknown").upper()
        summary  = result.get("summary", "(no summary)")

        agent_lines = [f"{label}: {verdict}", f"  Summary: {summary}"]

        # Agent-specific structured fields — add where relevant
        if key == "doc_auditor":
            issues = result.get("issues_found", [])
            if issues:
                agent_lines.append(f"  Issues found: {'; '.join(issues)}")

        elif key == "kyc_guardian":
            flags = result.get("flags_raised", [])
            if flags:
                agent_lines.append(f"  Flags raised: {'; '.join(flags)}")

        elif key == "dynamic_compliance":
            jur = result.get("jurisdiction", "")
            if jur:
                agent_lines.append(f"  Jurisdiction: {jur}")
            cits = result.get("citations", [])
            if cits:
                agent_lines.append(f"  Citations: {'; '.join(cits[:3])}")
            concerns = result.get("concerns", [])
            if concerns:
                agent_lines.append(f"  Concerns: {'; '.join(concerns)}")

        elif key == "stress_test":
            rl = result.get("risk_level", "")
            if rl:
                agent_lines.append(f"  Risk level: {rl}")
            rfs = result.get("risk_factors", [])
            if rfs:
                agent_lines.append(f"  Risk factors: {'; '.join(rfs[:3])}")

        elif key == "asset_tokenizer":
            std   = result.get("token_standard", "")
            total = result.get("total_tokens", 0)
            per_t = result.get("value_per_token_eur", 0.0)
            if std:
                agent_lines.append(f"  Standard: {std}")
            if total and per_t:
                implied = total * per_t
                agent_lines.append(
                    f"  Structure: {total:,} tokens × EUR {per_t:,.2f} "
                    f"= EUR {implied:,.0f}"
                )
            notes = result.get("structure_notes", [])
            if notes:
                agent_lines.append(f"  Notes: {'; '.join(notes[:2])}")

        lines.append("")
        lines.extend(agent_lines)

    # Seal status
    lines.extend([
        "",
        "SEAL STATUS",
        "-" * 40,
        f"Status: {seal.get('status', 'unknown')}",
    ])
    if seal.get("status") == "sealed":
        chash = seal.get("canonical_hash", "")
        lines.append(f"Canonical hash: {chash[:32]}...")
        lines.append(f"Sealed at: {seal.get('sealed_at', '')}")
        lines.append(f"Curve: {seal.get('curve', '')}")
    elif seal.get("status") == "blocked":
        lines.append(f"Failed gate: {seal.get('failed_gate', 'unknown')}")
        lines.append(f"Reason: {seal.get('reason', '')[:200]}")

    lines.extend([
        "",
        "=" * 50,
        "Generate the OrchestratorBriefing JSON for the Head of Digital Assets.",
        "Describe this completed decision faithfully. The decision is sealed and final.",
        "The Head of Digital Assets makes the final Approve/Reject — your briefing advises.",
    ])

    return "\n".join(lines)


# ── Templated fallback ─────────────────────────────────────────────────────────

def _build_templated_briefing(decision_record: dict) -> dict:
    """
    Build a fully deterministic briefing from decision_record fields.

    Called when both Opus and Sonnet are unavailable, or on any unexpected
    synthesis error. Produces a structurally complete briefing (all four
    schema fields populated) from the existing decision_record data alone.
    No LLM, no network, no external dependency.
    """
    status  = decision_record.get("pipeline_status", "unknown")
    reason  = decision_record.get("gate_reason", "See agent summaries for details.")
    agents  = decision_record.get("agents", {})
    seal    = decision_record.get("seal") or {}

    # ── Headline ──────────────────────────────────────────────────────────────
    if status == "approved_pending_human":
        headline = (
            "APPROVED PENDING HUMAN REVIEW — "
            "All five compliance gates cleared; asset tokenisation structure proposed."
        )
    elif status == "halted_kyc":
        kyc_sum = agents.get("kyc_guardian", {}).get("summary", "KYC Guardian issued a HALT verdict.")
        headline = f"HALTED — KYC Guardian HALT; pipeline stopped. {kyc_sum[:120]}"
    elif status == "blocked_gate":
        failed = seal.get("failed_gate", "")
        if failed:
            headline = f"BLOCKED — gate '{failed}' failed; no tokenisation and no seal produced."
        else:
            headline = "BLOCKED — mandatory compliance gate(s) failed; tokenisation not approved."
    elif status == "error":
        headline = "PIPELINE ERROR — unexpected failure during pipeline execution."
    else:
        headline = f"PIPELINE STATUS: {status}."

    # ── Decisive factor ───────────────────────────────────────────────────────
    decisive_factor = reason[:300] if reason else "See individual agent verdicts."

    # ── Per-agent summary ──────────────────────────────────────────────────────
    per_agent: list[str] = []
    for key, label in _AGENT_LABELS:
        result = agents.get(key)
        if result is None:
            continue
        verdict  = result.get("verdict", "unknown").upper()
        summary  = result.get("summary", "(no summary)")
        # Cap summary length for readability
        summary_short = summary[:120] + ("…" if len(summary) > 120 else "")
        per_agent.append(f"{label}: {verdict} — {summary_short}")

    if not per_agent:
        per_agent = ["No agent verdicts available — pipeline did not produce results."]

    # ── Recommendation ────────────────────────────────────────────────────────
    if status == "approved_pending_human":
        recommendation = (
            "All five mandatory compliance gates cleared and the ECDSA seal was produced. "
            "Review the full decision record and proposed token structure before issuing "
            "a final Approve or Reject. The final decision rests with the Head of Digital Assets."
        )
    elif status == "halted_kyc":
        recommendation = (
            "The KYC Guardian issued a HALT verdict — this is the most severe compliance outcome. "
            "Immediately escalate to the Compliance and Legal teams before any further action. "
            "Do NOT approve tokenisation. The Head of Digital Assets should confirm the escalation "
            "path with the Chief Compliance Officer."
        )
    elif status == "blocked_gate":
        failed_gate = seal.get("failed_gate", "one or more mandatory gates")
        recommendation = (
            f"Gate '{failed_gate}' blocked the pipeline — no seal was produced. "
            "Tokenisation cannot proceed until the identified issues are resolved and the case "
            "is resubmitted. The Head of Digital Assets should determine the remediation path "
            "in consultation with the relevant specialist team."
        )
    else:
        recommendation = (
            "Review the full decision record and consult the relevant specialist teams "
            "before taking any action. The final decision rests with the Head of Digital Assets."
        )

    return {
        "headline":          headline,
        "decisive_factor":   decisive_factor,
        "per_agent_summary": per_agent,
        "recommendation":    recommendation,
        "source":            "templated_fallback",
        "model_used":        "none",
        "was_fallback":      False,
        "latency_ms":        0,
    }


# ── Public interface ───────────────────────────────────────────────────────────

def synthesize_briefing(decision_record: dict) -> dict:
    """
    Run Layer 2 LLM synthesis on the completed, sealed decision_record.

    Attempts Claude Opus 4.8 → Claude Sonnet 4.6 (via existing failover engine).
    On any failure — including ModelUnavailableError, missing API key, network
    error, or unexpected exception — returns a deterministic templated briefing
    built from the decision_record fields. This function never raises.

    Args:
        decision_record: The complete dict returned by run_pipeline() Layer 1.
                         Must be fully formed (pipeline_status set, seal attached).

    Returns:
        {
            headline:          str   — one-line outcome statement
            decisive_factor:   str   — most important reason for the outcome
            per_agent_summary: list  — one line per agent that ran
            recommendation:    str   — advised action, deferred to the human
            source:            str   — "llm" | "templated_fallback"
            model_used:        str   — model ID or "none"
            was_fallback:      bool  — True if Sonnet carried the call
            latency_ms:        int   — synthesis latency (0 for templated)
        }
    """
    req_id = decision_record.get("request_id", "UNKNOWN")
    logger.info("synthesis: starting Layer 2 briefing for %s", req_id)

    try:
        prompt = _build_synthesis_prompt(decision_record)
        response = call_agent_model(
            "orchestrator", prompt, _SYSTEM_PROMPT,
            schema=OrchestratorBriefing,
        )
        data: OrchestratorBriefing = response.data

        logger.info(
            "synthesis: %s → briefing ready model=%s fallback=%s latency_ms=%d",
            req_id, response.model_used, response.was_fallback, response.latency_ms,
        )
        return {
            "headline":          data.headline,
            "decisive_factor":   data.decisive_factor,
            "per_agent_summary": data.per_agent_summary,
            "recommendation":    data.recommendation,
            "source":            "llm",
            "model_used":        response.model_used,
            "was_fallback":      response.was_fallback,
            "latency_ms":        response.latency_ms,
        }

    except ModelUnavailableError as exc:
        logger.error(
            "synthesis: all models unavailable for %s — using templated fallback. %s",
            req_id, exc,
        )

    except Exception as exc:
        logger.error(
            "synthesis: unexpected error for %s — using templated fallback. %s",
            req_id, exc, exc_info=True,
        )

    return _build_templated_briefing(decision_record)
