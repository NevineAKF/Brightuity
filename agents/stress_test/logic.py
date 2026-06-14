"""
agents/stress_test/logic.py
Brightuity — Stress-Test Simulator agent.

Quantitative market and liquidity risk assessment for RWA tokenisation requests.
Evaluates price volatility, liquidity depth, concentration risk, and asset-class-
specific structural risk factors. Scope is market/liquidity risk ONLY — not KYC,
documents, or regulatory compliance.

Model: DeepSeek-V4-Pro (json_object mode) on Featherless as primary;
       Qwen/Qwen3.6-27B (plain mode) as fallback.

Public interface:
    run_stress_test(client_record: dict) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import StressTestVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Fields this agent reads from the client record.
# KYC fields, document fields, source_of_funds, and expected_outcome are excluded.
# Risk scope only: asset characteristics + pre-screened risk flags.
_STRESS_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "risk_flags",
})


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_prompt(client_record: dict) -> str:
    """
    Build the user-turn prompt from market/liquidity-risk-relevant fields only.

    KYC fields, document fields, source_of_funds, and expected_outcome are
    never referenced here — they cannot reach the model.
    """
    r = client_record
    risk_flags = r.get("risk_flags", [])
    flags_text = (
        "\n".join(f"  • {f}" for f in risk_flags)
        if risk_flags
        else "  None detected."
    )
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    return (
        "STRESS-TEST ASSESSMENT REQUEST\n\n"
        f"Request ID     : {r.get('request_id', 'UNKNOWN')}\n\n"
        "ASSET UNDER REVIEW\n"
        f"  Type   : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Detail : {r.get('asset_detail', 'UNKNOWN')}\n"
        f"  Value  : {value_display}\n\n"
        f"PRE-SCREENED RISK FLAGS:\n{flags_text}\n\n"
        "Assess market and liquidity risk for this asset. "
        "Deliver your verdict in the required JSON format."
    )


# ── Public interface ───────────────────────────────────────────────────────────

def run_stress_test(client_record: dict) -> dict:
    """
    Run the Stress-Test Simulator against one client record.

    Uses StressTestVerdict schema. Primary model DeepSeek-V4-Pro uses
    json_object mode (response_format={"type":"json_object"}); fallback
    Qwen/Qwen3.6-27B uses plain mode (no response_format, <think> stripped).

    Returns:
        {
            "agent":        "stress_test",
            "verdict":      "pass" | "fail",
            "summary":      str,
            "risk_level":   "low" | "medium" | "high" | "critical",
            "risk_factors": list[str],
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        On ModelUnavailableError → fail/critical — a model outage must never
        silently clear a risk gate.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("stress_test: starting assessment for %s", request_id)

    prompt = _build_prompt(client_record)

    try:
        response = call_agent_model(
            "stress_test", prompt, _SYSTEM_PROMPT,
            schema=StressTestVerdict,
        )
    except ModelUnavailableError as exc:
        logger.error(
            "stress_test: all models unavailable for %s — %s", request_id, exc
        )
        return {
            "agent": "stress_test",
            "verdict": "fail",
            "summary": (
                "All models unavailable — risk assessment cannot be completed. "
                f"Escalating to human reviewer. Detail: {exc}"
            ),
            "risk_level": "critical",
            "risk_factors": ["model_unavailable"],
            "model_used": "none",
            "was_fallback": False,
            "latency_ms": 0,
        }

    data: StressTestVerdict = response.data

    logger.info(
        "stress_test: %s → verdict=%s risk_level=%s model=%s fallback=%s latency_ms=%d",
        request_id, data.verdict, data.risk_level,
        response.model_used, response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "stress_test",
        "verdict": data.verdict,
        "summary": data.summary,
        "risk_level": data.risk_level,
        "risk_factors": data.risk_factors,
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
