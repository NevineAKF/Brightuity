"""
agents/doc_auditor/logic.py
Brightuity — Doc Auditor agent.

First compliance gate. Examines asset documentation for RWA tokenisation requests:
completeness, ownership-chain integrity, asset identification, valuation support.
Scope is documents only — KYC, sanctions, and risk are handled by other agents.

Public interface:
    audit_documents(client_record: dict) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import DocAuditorVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Exact fields passed to the model. Everything else — including expected_outcome,
# kyc_status, kyc_flags, risk_flags, source_of_funds — is deliberately excluded.
_DOC_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "encrypted_doc_id",
    "submitted_at",
    "full_name",        # appears on the actual deeds; needed for coherent summary
    "nationality",      # determines the regulatory jurisdiction for required docs
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "documents_status",
    "document_issues",
})


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_prompt(client_record: dict) -> str:
    """
    Build the user-turn prompt from document-relevant fields only.

    Fields outside _DOC_FIELDS are never referenced here, so expected_outcome
    and KYC/risk data cannot reach the model regardless of what is in the record.
    """
    r = client_record
    issues = r.get("document_issues", [])
    issues_text = (
        "\n".join(f"  • {issue}" for issue in issues)
        if issues
        else "  None recorded."
    )
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    return (
        "DOCUMENT AUDIT REQUEST\n\n"
        f"Request ID          : {r.get('request_id', 'UNKNOWN')}\n"
        f"Document Reference  : {r.get('encrypted_doc_id', 'UNKNOWN')}\n"
        f"Applicant Name      : {r.get('full_name', 'UNKNOWN')}\n"
        f"Applicant Nationality: {r.get('nationality', 'UNKNOWN')}\n"
        f"Submitted           : {r.get('submitted_at', 'UNKNOWN')}\n\n"
        "ASSET UNDER REVIEW\n"
        f"  Type    : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Detail  : {r.get('asset_detail', 'UNKNOWN')}\n"
        f"  Value   : {value_display}\n\n"
        f"DOCUMENT STATUS : {r.get('documents_status', 'UNKNOWN')}\n"
        f"DOCUMENT ISSUES :\n{issues_text}\n\n"
        "Deliver your document audit verdict in the required JSON format."
    )


# ── Public interface ───────────────────────────────────────────────────────────

def audit_documents(client_record: dict) -> dict:
    """
    Run the Doc Auditor against one client record.

    Builds a prompt from document-relevant fields only (expected_outcome and
    KYC/risk fields are never passed to the model), calls call_agent_model
    with the DocAuditorVerdict schema, and returns the structured verdict dict.

    The engine enforces the JSON contract (plain mode for Featherless/Qwen3).
    No local parsing is needed — the engine's normalize+validate layer handles
    <think> stripping and JSON extraction before returning a validated object.

    Returns:
        {
            "agent":        "doc_auditor",
            "verdict":      "pass" | "fail",
            "summary":      str,
            "issues_found": list[str],
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        On ModelUnavailableError: fail verdict with "model_unavailable" in issues_found.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("doc_auditor: starting audit for %s", request_id)

    prompt = _build_prompt(client_record)

    try:
        response = call_agent_model(
            "doc_auditor", prompt, _SYSTEM_PROMPT, schema=DocAuditorVerdict
        )
    except ModelUnavailableError as exc:
        logger.error("doc_auditor: all models unavailable for %s — %s", request_id, exc)
        return {
            "agent": "doc_auditor",
            "verdict": "fail",
            "summary": (
                "All models unavailable (primary exhausted, fallback exhausted). "
                f"Escalating to human reviewer. Detail: {exc}"
            ),
            "issues_found": ["model_unavailable"],
            "model_used": "none",
            "was_fallback": False,
            "latency_ms": 0,
        }

    data: DocAuditorVerdict = response.data

    logger.info(
        "doc_auditor: %s → verdict=%s model=%s fallback=%s latency_ms=%d",
        request_id, data.verdict, response.model_used,
        response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "doc_auditor",
        "verdict": data.verdict,
        "summary": data.summary,
        "issues_found": data.issues_found,
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
