"""
agents/asset_tokenizer/logic.py
Brightuity — Asset Tokenizer agent.

Designs the on-chain tokenisation structure for a real-world asset that has
passed all prior compliance gates (Doc Auditor, KYC Guardian, Dynamic
Compliance, Stress-Test Simulator). Proposes the token standard, total supply,
per-token denomination, and key structural parameters.

This agent does NOT make the final issuance decision and does NOT mint tokens.
It produces a structure recommendation for review and sign-off by the Head of
Digital Assets. Scope is tokenisation structure design ONLY — not KYC, market
risk, or regulatory compliance.

Model: zai-org/GLM-4.6 (plain mode) on Featherless as primary;
       Qwen/Qwen3.6-27B (plain mode) as fallback.
       (Kimi-K2.6 demoted 2026-06-14: correct output but 2–4 min/call, too slow.)

Public interface:
    design_token_structure(client_record: dict) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import AssetTokenizerVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Fields this agent reads from the client record.
# KYC, document, source-of-funds, risk, and expected_outcome fields are
# deliberately excluded — the tokenizer sees asset characteristics only.
_TOKENIZER_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "nationality",    # jurisdiction context for transfer restriction design
})


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_prompt(client_record: dict) -> str:
    """
    Build the user-turn prompt from asset-relevant fields only.

    KYC, document, source-of-funds, risk_flags, and expected_outcome are
    never referenced here and cannot reach the model.
    """
    r = client_record
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    return (
        "TOKEN STRUCTURE DESIGN REQUEST\n\n"
        f"Request ID     : {r.get('request_id', 'UNKNOWN')}\n\n"
        "ASSET UNDER REVIEW\n"
        f"  Type         : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Detail       : {r.get('asset_detail', 'UNKNOWN')}\n"
        f"  Stated Value : {value_display}\n"
        f"  Jurisdiction : {r.get('nationality', 'UNKNOWN')} (EU regulatory framework)\n\n"
        "All prior compliance gates (document audit, KYC, regulatory compliance, "
        "market risk) are assumed to have passed for this request.\n\n"
        "Design the tokenisation structure for this asset and deliver your proposal "
        "in the required JSON format."
    )


# ── Public interface ───────────────────────────────────────────────────────────

def design_token_structure(client_record: dict) -> dict:
    """
    Run the Asset Tokenizer against one client record.

    Uses AssetTokenizerVerdict schema. Both primary (GLM-4.6) and fallback
    (Qwen/Qwen3.6-27B) use plain mode on Featherless — no response_format
    header, with <think> stripping and JSON fence extraction handled by the
    engine's normalize+validate layer.

    Returns:
        {
            "agent":                "asset_tokenizer",
            "verdict":              "pass" | "fail",
            "summary":              str,
            "token_standard":       str,
            "total_tokens":         int,
            "value_per_token_eur":  float,
            "structure_notes":      list[str],
            "model_used":           str,
            "was_fallback":         bool,
            "latency_ms":           int,
        }

        On ModelUnavailableError → fail verdict with zero numeric fields.
        A structurer that cannot run must never propose a phantom structure.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("asset_tokenizer: starting structure design for %s", request_id)

    prompt = _build_prompt(client_record)

    try:
        response = call_agent_model(
            "asset_tokenizer", prompt, _SYSTEM_PROMPT,
            schema=AssetTokenizerVerdict,
        )
    except ModelUnavailableError as exc:
        logger.error(
            "asset_tokenizer: all models unavailable for %s — %s", request_id, exc
        )
        return {
            "agent": "asset_tokenizer",
            "verdict": "fail",
            "summary": (
                "All models unavailable — token structure cannot be proposed. "
                f"Escalating to human reviewer. Detail: {exc}"
            ),
            "token_standard": "unknown",
            "total_tokens": 0,
            "value_per_token_eur": 0.0,
            "structure_notes": ["model_unavailable"],
            "model_used": "none",
            "was_fallback": False,
            "latency_ms": 0,
        }

    data: AssetTokenizerVerdict = response.data

    logger.info(
        "asset_tokenizer: %s → verdict=%s tokens=%d @EUR%.2f model=%s fallback=%s latency_ms=%d",
        request_id, data.verdict, data.total_tokens, data.value_per_token_eur,
        response.model_used, response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "asset_tokenizer",
        "verdict": data.verdict,
        "summary": data.summary,
        "token_standard": data.token_standard,
        "total_tokens": data.total_tokens,
        "value_per_token_eur": data.value_per_token_eur,
        "structure_notes": data.structure_notes,
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
