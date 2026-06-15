"""
agents/stress_test/logic.py
Brightuity — Stress-Test Simulator agent.

Quantitative market and liquidity risk assessment for RWA tokenisation requests.
Evaluates price volatility, liquidity depth, concentration risk, and asset-class-
specific structural risk factors. Scope is market/liquidity risk ONLY — not KYC,
documents, or regulatory compliance.

Architecture:
  1. Deterministic risk engine (risk_engine.py) runs FIRST — computes risk_score,
     risk_level, verdict, and stress scenarios from parametric formulas.
  2. Engine output is injected into the LLM prompt as established fact.
  3. LLM (DeepSeek-V4-Pro primary, Qwen fallback) provides the interpretive
     narrative only: summary + enriched risk_factors. It cannot alter engine numbers.

Model: DeepSeek-V4-Pro (json_object mode) on Featherless as primary;
       Qwen/Qwen3.6-27B (plain mode) as fallback.

Public interface:
    run_stress_test(client_record: dict) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path

from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import StressTestNarrative
from agents.stress_test.risk_engine import compute_risk_metrics

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Fields this agent reads from the client record.
# KYC fields, document fields, source_of_funds, and expected_outcome are excluded.
_STRESS_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "risk_flags",
})


# ── Prompt construction ────────────────────────────────────────────────────────

def _build_risk_block(rm: dict) -> str:
    """Format the deterministic engine output as an injected fact block."""
    sv  = rm["stressed_value_range"]
    sc  = rm["score_components"]
    scn = rm["market_stress_scenarios"]
    base = rm["base_valuation"]
    worst = sv["worst_case_eur"]
    worst_pct = (worst - base) / base * 100 if base else 0.0
    ir_pct = rm["market_volatility"] * 1.5

    lines = [
        "DETERMINISTIC RISK ENGINE OUTPUT",
        "-" * 52,
        "Engine: Brightuity Parametric Risk Engine v1.0",
        "",
        "ASSET CLASSIFICATION",
        f"  Asset type              : {rm['asset_type']}",
        f"  Illiquidity discount    : {rm['illiquidity_discount']:.0%}  (forced-sale haircut)",
        f"  Annual market volatility: {rm['market_volatility']:.0%}  (parametric estimate)",
        "",
        "RISK SCORE COMPOSITION  (scale 0-100)",
        f"  Illiquidity component   : {sc['illiquidity_score']:3d}  (asset-class illiquidity penalty)",
        f"  Volatility component    : {sc['volatility_score']:3d}  (annualised price volatility)",
        f"  Concentration component : {sc['concentration_score']:3d}  (single-asset EUR {base:,.0f})",
        f"  Risk flags component    : {sc['flags_score']:3d}  ({sc['flags_score'] // 10} pre-screened flag(s) x 10 pts)",
        f"  -----------------------------------------",
        f"  TOTAL RISK SCORE        : {rm['risk_score']:3d}  ->  RISK LEVEL: {rm['risk_level'].upper()}",
        "",
        f"STRESS SCENARIOS  (base: EUR {base:,.0f})",
        f"  Market downturn (-20%)                              : EUR {scn['market_downturn_20pct_eur']:>12,.0f}",
        f"  Liquidity crisis (-20% + {rm['illiquidity_discount']:.0%} illiq discount)     : EUR {scn['liquidity_crisis_eur']:>12,.0f}",
        f"  Interest rate shock (-{ir_pct:.0%}, vol x 1.5)           : EUR {scn['interest_rate_shock_eur']:>12,.0f}",
        "",
        "STRESSED VALUE RANGE",
        f"  Worst case              : EUR {sv['worst_case_eur']:>12,.0f}  ({worst_pct:+.1f}% vs base)",
        f"  Base case               : EUR {sv['base_case_eur']:>12,.0f}",
        f"  Best case (+10%)        : EUR {sv['best_case_eur']:>12,.0f}  (+10.0% vs base)",
        "",
        f"ENGINE VERDICT: {rm['verdict'].upper()}  |  RISK LEVEL: {rm['risk_level'].upper()}",
        "",
        "ENGINE-COMPUTED RISK FACTORS:",
    ]
    for f in rm["risk_factors"]:
        lines.append(f"  - {f}")

    lines += [
        "",
        "INSTRUCTION: The above figures are DETERMINISTIC ENGINE OUTPUTS. Do NOT",
        "re-derive, alter, or contradict them. Write a concise risk narrative",
        "(summary) for the Head of Digital Assets that explains WHAT these numbers",
        "mean and WHY they matter for this tokenisation request. Also provide",
        "specific, enriched risk_factors that contextualise the engine findings.",
        "Your JSON output must contain ONLY 'summary' and 'risk_factors'.",
    ]
    return "\n".join(lines)


def _build_prompt(client_record: dict, risk_metrics: dict) -> str:
    """
    Build the user-turn prompt.

    The deterministic engine block is injected first as established fact.
    KYC fields, document fields, source_of_funds, and expected_outcome are
    never referenced here — they cannot reach the model.
    """
    r = client_record
    risk_flags = r.get("risk_flags", [])
    flags_text = (
        "\n".join(f"  - {f}" for f in risk_flags)
        if risk_flags
        else "  None detected."
    )
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    risk_block = _build_risk_block(risk_metrics)

    return (
        "STRESS-TEST ASSESSMENT REQUEST\n\n"
        f"Request ID     : {r.get('request_id', 'UNKNOWN')}\n\n"
        "ASSET UNDER REVIEW\n"
        f"  Type   : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Detail : {r.get('asset_detail', 'UNKNOWN')}\n"
        f"  Value  : {value_display}\n\n"
        f"PRE-SCREENED RISK FLAGS:\n{flags_text}\n\n"
        f"{risk_block}\n\n"
        "Deliver your risk narrative in the required JSON format "
        "(summary + risk_factors only — no verdict, no risk_level)."
    )


# ── Public interface ───────────────────────────────────────────────────────────

def run_stress_test(client_record: dict) -> dict:
    """
    Run the Stress-Test Simulator against one client record.

    Step 1: compute_risk_metrics() runs deterministically — risk_score,
            risk_level, verdict, and stress scenarios are fixed here.
    Step 2: LLM call (DeepSeek-V4-Pro primary, Qwen fallback) produces
            only the interpretive narrative: summary + risk_factors.
    Step 3: Return dict merges engine values (verdict/risk_level) with
            LLM values (summary/risk_factors) and appends risk_metrics.

    Returns:
        {
            "agent":        "stress_test",
            "verdict":      "pass" | "fail",       <- ENGINE
            "summary":      str,                    <- LLM
            "risk_level":   "low" | ... | "critical", <- ENGINE
            "risk_factors": list[str],              <- LLM (enriched)
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
            "risk_metrics": dict,                   <- full engine output
        }

        On ModelUnavailableError -> fail/critical (engine values preserved;
        LLM narrative replaced by a fallback message). A model outage must
        never silently clear a risk gate.
    """
    request_id = client_record.get("request_id", "UNKNOWN")
    logger.info("stress_test: starting assessment for %s", request_id)

    risk_metrics = compute_risk_metrics(client_record)
    logger.info(
        "stress_test: %s — risk_score=%d risk_level=%s verdict=%s",
        request_id, risk_metrics["risk_score"],
        risk_metrics["risk_level"], risk_metrics["verdict"],
    )

    prompt = _build_prompt(client_record, risk_metrics)

    try:
        response = call_agent_model(
            "stress_test", prompt, _SYSTEM_PROMPT,
            schema=StressTestNarrative,
        )
    except ModelUnavailableError as exc:
        logger.error(
            "stress_test: all models unavailable for %s — %s", request_id, exc
        )
        return {
            "agent":        "stress_test",
            "verdict":      risk_metrics["verdict"],
            "summary": (
                f"All models unavailable — LLM narrative cannot be produced. "
                f"Engine verdict: {risk_metrics['verdict']} / "
                f"risk_level: {risk_metrics['risk_level']} / "
                f"risk_score: {risk_metrics['risk_score']}. "
                f"Escalating to human reviewer. Detail: {exc}"
            ),
            "risk_level":   risk_metrics["risk_level"],
            "risk_factors": risk_metrics["risk_factors"],
            "model_used":   "none",
            "was_fallback": False,
            "latency_ms":   0,
            "risk_metrics": risk_metrics,
        }

    data: StressTestNarrative = response.data

    logger.info(
        "stress_test: %s -> verdict=%s risk_level=%s model=%s fallback=%s latency_ms=%d",
        request_id, risk_metrics["verdict"], risk_metrics["risk_level"],
        response.model_used, response.was_fallback, response.latency_ms,
    )

    return {
        "agent":        "stress_test",
        "verdict":      risk_metrics["verdict"],       # engine-authoritative
        "summary":      data.summary,                  # LLM interpretive narrative
        "risk_level":   risk_metrics["risk_level"],    # engine-authoritative
        "risk_factors": data.risk_factors,             # LLM enriched factors
        "model_used":   response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms":   response.latency_ms,
        "risk_metrics": risk_metrics,
    }
