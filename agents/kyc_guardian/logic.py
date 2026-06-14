"""
agents/kyc_guardian/logic.py
Brightuity — KYC Guardian agent.

Most sensitive compliance gate. Screens applicants for identity integrity,
sanctions hits, PEP status, and source-of-funds legitimacy under EU AMLD5/AMLD6
and FATF standards.

A "halt" verdict triggers a hard pipeline stop — no further agents run,
no token can be issued without full compliance investigation and human sign-off.
Scope is KYC/AML/sanctions/source-of-funds ONLY — not documents, not risk.

Public interface:
    screen_kyc(client_record: dict) -> dict
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Exact fields passed to the model. Documents, risk_flags, and expected_outcome
# are deliberately excluded — each agent sees only its own scope.
_KYC_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "full_name",
    "date_of_birth",     # age verification, identity coherence
    "nationality",       # jurisdiction risk under FATF categories
    "kyc_status",        # system-recorded verdict: clean / pep_match / sanctions_adjacent / etc.
    "kyc_flags",         # specific flag strings from upstream identity checks
    "source_of_funds",   # stated origin of wealth
    "source_verifiable", # boolean — upstream verification result
    "asset_value_eur",   # AML threshold context (>EUR 1M triggers enhanced scrutiny)
    "asset_type",        # source-of-funds plausibility context
})


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_prompt(client_record: dict) -> str:
    """
    Build the user-turn prompt from KYC-relevant fields only.

    expected_outcome, documents_status, document_issues, and risk_flags are
    never referenced here and cannot reach the model.
    """
    r = client_record
    flags = r.get("kyc_flags", [])
    flags_text = (
        "\n".join(f"  • {f}" for f in flags)
        if flags
        else "  None recorded."
    )
    verifiable = r.get("source_verifiable", None)
    verifiable_display = (
        "Yes" if verifiable is True
        else "No" if verifiable is False
        else "Unknown"
    )
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    return (
        "KYC SCREENING REQUEST\n\n"
        f"Request ID          : {r.get('request_id', 'UNKNOWN')}\n"
        f"Applicant Name      : {r.get('full_name', 'UNKNOWN')}\n"
        f"Date of Birth       : {r.get('date_of_birth', 'UNKNOWN')}\n"
        f"Nationality         : {r.get('nationality', 'UNKNOWN')}\n\n"
        f"KYC STATUS          : {r.get('kyc_status', 'UNKNOWN')}\n"
        f"KYC FLAGS           :\n{flags_text}\n\n"
        f"SOURCE OF FUNDS     : {r.get('source_of_funds', 'UNKNOWN')}\n"
        f"SOURCE VERIFIABLE   : {verifiable_display}\n\n"
        "ASSET CONTEXT\n"
        f"  Type  : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Value : {value_display}\n\n"
        "Deliver your KYC screening verdict in the required JSON format."
    )


# ── Response parsing ───────────────────────────────────────────────────────────

def _parse_verdict(raw: str) -> tuple[str, str, list[str]]:
    """
    Parse the model's JSON response into (verdict, summary, flags_raised).

    Accepts three valid verdict values: "pass", "fail", "halt".
    Handles <think> blocks, markdown fences, and surrounding prose.
    Falls back to ("halt", error_message, ["json_parse_error"]) on bad output —
    defaulting to halt rather than pass on a parse failure is the conservative,
    bank-grade safe choice.
    """
    text = raw.strip()

    # Strip reasoning-model think blocks (Claude reasoning, DeepSeek, Qwen3)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Extract the first complete JSON object — handles any surrounding text
    brace_start = text.find("{")
    brace_end = text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        text = text[brace_start:brace_end]

    try:
        data = json.loads(text)
        verdict = str(data.get("verdict", "halt")).lower().strip()
        if verdict not in ("pass", "fail", "halt"):
            logger.warning(
                "kyc_guardian: unexpected verdict value %r — defaulting to halt", verdict
            )
            verdict = "halt"
        summary = str(data.get("summary", "")).strip() or "No summary provided."
        flags_raised = [str(f) for f in data.get("flags_raised", [])]
        return verdict, summary, flags_raised

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning(
            "kyc_guardian: JSON parse failed (%s). Raw response (first 400 chars): %.400s",
            exc, raw,
        )
        return (
            "halt",
            "Parse error: model response was not valid JSON. Defaulting to halt — manual review required.",
            ["json_parse_error"],
        )


# ── Public interface ───────────────────────────────────────────────────────────

def screen_kyc(client_record: dict) -> dict:
    """
    Run the KYC Guardian against one client record.

    Builds a prompt from KYC-relevant fields only (expected_outcome, document
    fields, and risk_flags are never passed to the model), calls call_agent_model
    with the "kyc_guardian" agent name (claude-opus-4-8 → gpt-4o failover on
    AI/ML API as configured in shared/config.py), and parses the JSON verdict.

    Args:
        client_record: One client dict from brightuity_clients.json (or DB1).
                       The full record may contain any fields; only _KYC_FIELDS
                       are extracted for the prompt.

    Returns:
        Structured verdict dict compatible with ConsensusSigner.seal():
        {
            "agent":        "kyc_guardian",
            "verdict":      "pass" | "fail" | "halt",
            "summary":      str,
            "flags_raised": list[str],   # empty list when verdict is "pass"
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        "halt" means the Orchestrator must stop the pipeline immediately —
        no further agents run, no token is ever issued on this case.
        Both "fail" and "halt" block the Consensus Signer seal; "halt" carries
        the additional signal to terminate the pipeline entirely.

        On ModelUnavailableError, returns a "halt" verdict (not "fail") so that
        a silent infrastructure failure can never accidentally open a path to seal.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("kyc_guardian: starting screening for %s", request_id)

    prompt = _build_prompt(client_record)

    try:
        response = call_agent_model("kyc_guardian", prompt, _SYSTEM_PROMPT)
    except ModelUnavailableError as exc:
        logger.error(
            "kyc_guardian: all models unavailable for %s — %s", request_id, exc
        )
        # Fail to halt: a model outage must never silently allow KYC to be bypassed.
        return {
            "agent": "kyc_guardian",
            "verdict": "halt",
            "summary": (
                "All models unavailable (primary and fallback exhausted). "
                "Defaulting to halt — KYC cannot be bypassed by an infrastructure failure. "
                f"Detail: {exc}"
            ),
            "flags_raised": ["model_unavailable"],
            "model_used": "none",
            "was_fallback": False,
            "latency_ms": 0,
        }

    verdict, summary, flags_raised = _parse_verdict(response.text)

    logger.info(
        "kyc_guardian: %s → verdict=%s model=%s fallback=%s latency_ms=%d",
        request_id,
        verdict,
        response.model_used,
        response.was_fallback,
        response.latency_ms,
    )

    return {
        "agent": "kyc_guardian",
        "verdict": verdict,
        "summary": summary,
        "flags_raised": flags_raised,
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
