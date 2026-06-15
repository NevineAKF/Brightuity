"""
agents/stress_test/risk_engine.py
Brightuity — Deterministic parametric risk engine for the Stress-Test Simulator.

Computes defensible, reproducible risk metrics from asset characteristics alone.
No randomness, no LLM, no I/O. Same inputs produce identical outputs every run.

logic.py injects the computed metrics into the LLM prompt as established fact.
The LLM interprets and narrates them — it cannot alter the computed values.

Public interface:
    compute_risk_metrics(client_record: dict) -> dict
"""

from __future__ import annotations

# ── Asset-type parameter table ─────────────────────────────────────────────────
# illiquidity_discount  : forced-sale haircut fraction vs fair value  (industry standard)
# market_volatility     : annualised price-return volatility fraction  (parametric estimate)
# illiquidity_score     : risk-score contribution from illiquidity     (0-40 range)
# volatility_score      : risk-score contribution from price volatility (0-25 range)
# liquidity_description : plain-text rationale used in risk_factors strings

_ASSET_PARAMS: dict[str, dict] = {
    "Commercial Property": {
        "illiquidity_discount": 0.10,
        "market_volatility":    0.12,
        "illiquidity_score":    13,
        "volatility_score":     17,
        "liquidity_description": (
            "90-180 day sale cycle; income-dependent valuation; "
            "tenant/vacancy risk in the tokenised portfolio"
        ),
    },
    "Residential Property": {
        "illiquidity_discount": 0.07,
        "market_volatility":    0.10,
        "illiquidity_score":    9,
        "volatility_score":     14,
        "liquidity_description": (
            "More liquid than commercial but physical settlement takes 30-90 days; "
            "Southern EU residential markets exhibit elevated historic price volatility"
        ),
    },
    "Luxury Villa": {
        "illiquidity_discount": 0.20,
        "market_volatility":    0.18,
        "illiquidity_score":    27,
        "volatility_score":     25,
        "liquidity_description": (
            "Highly illiquid; narrow buyer pool; luxury segment amplifies downturns "
            "disproportionately; offshore hub locations (Cyprus, Malta) add price opacity"
        ),
    },
    "Gold Reserve": {
        "illiquidity_discount": 0.03,
        "market_volatility":    0.18,
        "illiquidity_score":    4,
        "volatility_score":     25,
        "liquidity_description": (
            "Underlying commodity is liquid but XAU/USD price volatility is high; "
            "tokenisation introduces basis risk vs spot; custody and insurance costs add drag"
        ),
    },
    "Private Equity": {
        "illiquidity_discount": 0.25,
        "market_volatility":    0.22,
        "illiquidity_score":    33,
        "volatility_score":     25,
        "liquidity_description": (
            "Lowest liquidity across all asset classes; fund lock-up periods preclude early exit; "
            "NAV-based valuation lags market reality by multiple quarters; no secondary price until exit"
        ),
    },
    "Fine Art Collection": {
        "illiquidity_discount": 0.30,
        "market_volatility":    0.25,
        "illiquidity_score":    40,
        "volatility_score":     25,
        "liquidity_description": (
            "Extremely illiquid; no exchange market; auction-based price discovery only; "
            "condition, provenance, and taste risk; cannot be used as formal collateral"
        ),
    },
}

# Fallback when asset_type is not in the table (treated as illiquid alternative)
_DEFAULT_PARAMS: dict = {
    "illiquidity_discount": 0.15,
    "market_volatility":    0.15,
    "illiquidity_score":    20,
    "volatility_score":     20,
    "liquidity_description": "Unclassified asset type; treated conservatively as illiquid alternative investment",
}

# ── Risk-score thresholds → risk_level + verdict ───────────────────────────────
# Each tuple: (exclusive_upper_bound, risk_level, verdict)
# Verdict logic: low/medium/high are pass (manageable with standard controls);
#                critical is fail (exceeds programme tolerance).
_THRESHOLDS: list[tuple[int, str, str]] = [
    (30,  "low",      "pass"),
    (60,  "medium",   "pass"),
    (80,  "high",     "pass"),
    (101, "critical", "fail"),
]

# ── Stress scenario shock parameters ──────────────────────────────────────────
_MARKET_DOWNTURN_SHOCK    = 0.20   # broad market drawdown scenario: -20%
_INTEREST_RATE_VOL_FACTOR = 1.50   # rate shock ≈ vol × 1.5 (duration-proxy)
_BEST_CASE_UPLIFT         = 0.10   # favourable market scenario: +10%


# ── Value-tier concentration score ────────────────────────────────────────────
# Single-asset concentration is structurally present for all cases;
# value size increases the score penalty because larger exposures have
# thinner buyer pools and higher impact on the issuer balance sheet.

def _concentration_score(asset_value_eur: float) -> int:
    if asset_value_eur <= 500_000:     return 2
    if asset_value_eur <= 1_000_000:   return 5
    if asset_value_eur <= 2_000_000:   return 8
    if asset_value_eur <= 5_000_000:   return 12
    if asset_value_eur <= 10_000_000:  return 16
    return 20


# ── Public interface ───────────────────────────────────────────────────────────

def compute_risk_metrics(client_record: dict) -> dict:
    """
    Compute deterministic parametric risk metrics for one client record.

    Reads: asset_type, asset_value_eur, risk_flags.
    No network I/O, no randomness. Same inputs -> identical outputs every run.

    Risk score formula (0-100):
        risk_score = illiquidity_score        [0-40, asset-class fixed]
                   + volatility_score         [0-25, asset-class fixed]
                   + concentration_score      [2-20, value-tier lookup]
                   + flags_score              [10 per flag, capped 25]
        capped at 100.

    Thresholds: <30=low/pass, 30-59=medium/pass, 60-79=high/pass, >=80=critical/fail.

    Returns dict with keys:
        base_valuation, asset_type, illiquidity_discount, market_volatility,
        market_stress_scenarios, stressed_value_range, score_components,
        risk_score, risk_level, verdict, risk_factors, methodology.
    """
    asset_type  = client_record.get("asset_type", "Unknown")
    asset_value = float(client_record.get("asset_value_eur", 0))
    risk_flags  = list(client_record.get("risk_flags") or [])

    params      = _ASSET_PARAMS.get(asset_type, _DEFAULT_PARAMS)
    illiq_disc  = params["illiquidity_discount"]
    mkt_vol     = params["market_volatility"]
    illiq_score = params["illiquidity_score"]
    vol_score   = params["volatility_score"]

    conc_score  = _concentration_score(asset_value)
    flags_score = min(len(risk_flags) * 10, 25)

    # Composite risk score (0-100)
    risk_score = min(illiq_score + vol_score + conc_score + flags_score, 100)

    # Derive risk_level and verdict from fixed thresholds
    risk_level = "critical"
    verdict    = "fail"
    for upper, level, v in _THRESHOLDS:
        if risk_score < upper:
            risk_level = level
            verdict    = v
            break

    # Stress scenario valuations
    downturn_val = round(asset_value * (1 - _MARKET_DOWNTURN_SHOCK))
    liq_crisis   = round(asset_value * (1 - _MARKET_DOWNTURN_SHOCK) * (1 - illiq_disc))
    ir_shock     = round(asset_value * (1 - mkt_vol * _INTEREST_RATE_VOL_FACTOR))
    best_case    = round(asset_value * (1 + _BEST_CASE_UPLIFT))
    worst_case   = min(downturn_val, liq_crisis, ir_shock)

    worst_pct = (worst_case - asset_value) / asset_value * 100 if asset_value else 0.0

    # Deterministic risk factor strings (engine-generated, not LLM-generated)
    engine_factors: list[str] = [
        (
            f"Illiquidity ({asset_type}): {params['liquidity_description']}"
        ),
        (
            f"Forced-sale discount: {illiq_disc:.0%} haircut vs fair value "
            f"(industry standard for {asset_type})"
        ),
        (
            f"Market stress: worst-case scenario EUR {worst_case:,.0f} "
            f"({worst_pct:+.1f}% vs EUR {asset_value:,.0f} base)"
        ),
        (
            f"Single-asset concentration: EUR {asset_value:,.0f} in one {asset_type} — "
            f"no portfolio diversification benefit"
        ),
    ]
    for flag in risk_flags:
        engine_factors.append(f"Pre-screened risk flag: {flag}")

    return {
        "base_valuation":       asset_value,
        "asset_type":           asset_type,
        "illiquidity_discount": illiq_disc,
        "market_volatility":    mkt_vol,
        "market_stress_scenarios": {
            "market_downturn_20pct_eur": downturn_val,
            "liquidity_crisis_eur":      liq_crisis,
            "interest_rate_shock_eur":   ir_shock,
        },
        "stressed_value_range": {
            "worst_case_eur": worst_case,
            "base_case_eur":  int(asset_value),
            "best_case_eur":  best_case,
        },
        "score_components": {
            "illiquidity_score":   illiq_score,
            "volatility_score":    vol_score,
            "concentration_score": conc_score,
            "flags_score":         flags_score,
        },
        "risk_score":   risk_score,
        "risk_level":   risk_level,
        "verdict":      verdict,
        "risk_factors": engine_factors,
        "methodology": (
            f"risk_score = illiquidity_score({illiq_score}) "
            f"+ volatility_score({vol_score}) "
            f"+ concentration_score({conc_score}) "
            f"+ flags_score({flags_score}) = {risk_score}/100. "
            f"Thresholds: <30=low/pass, 30-59=medium/pass, "
            f"60-79=high/pass, >=80=critical/fail."
        ),
    }
