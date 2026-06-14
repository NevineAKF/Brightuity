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

import logging
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import KycGuardianVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Exact fields passed to the model. Documents, risk_flags, and expected_outcome
# are deliberately excluded — each agent sees only its own scope.
_KYC_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "full_name",
    "date_of_birth",
    "nationality",
    "kyc_status",
    "kyc_flags",
    "source_of_funds",
    "source_verifiable",
    "asset_value_eur",
    "asset_type",
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


# ── Public interface ───────────────────────────────────────────────────────────

def screen_kyc(client_record: dict) -> dict:
    """
    Run the KYC Guardian against one client record.

    Uses KycGuardianVerdict schema with json_schema strict mode (claude-opus-4-8
    primary, gpt-4o fallback — both on AI/ML API). The schema enforces the
    three-verdict enum ["pass","fail","halt"] at the API level.

    Returns:
        {
            "agent":        "kyc_guardian",
            "verdict":      "pass" | "fail" | "halt",
            "summary":      str,
            "flags_raised": list[str],
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        "halt" = hard pipeline stop. On ModelUnavailableError → "halt" (not
        "fail") because a silent infrastructure failure must never open a path
        to seal.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("kyc_guardian: starting screening for %s", request_id)

    prompt = _build_prompt(client_record)

    try:
        response = call_agent_model(
            "kyc_guardian", prompt, _SYSTEM_PROMPT, schema=KycGuardianVerdict
        )
    except ModelUnavailableError as exc:
        logger.error("kyc_guardian: all models unavailable for %s — %s", request_id, exc)
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

    data: KycGuardianVerdict = response.data

    logger.info(
        "kyc_guardian: %s → verdict=%s model=%s fallback=%s latency_ms=%d",
        request_id, data.verdict, response.model_used,
        response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "kyc_guardian",
        "verdict": data.verdict,
        "summary": data.summary,
        "flags_raised": data.flags_raised,
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
