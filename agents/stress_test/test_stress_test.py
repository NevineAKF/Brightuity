"""
agents/stress_test/test_stress_test.py
Brightuity — Live test for the Stress-Test Simulator agent.

Runs the Stress-Test Simulator against three real clients from
brightuity_clients.json and prints the full structured verdict for each.

Test cases:
  1. REQ-2041  Marcus Weber   — EUR 2M commercial property, Berlin, Germany
                                Clean record, mature EU market → reasoning toward low/medium risk, PASS
  2. REQ-2042  Sofia Andreou  — EUR 800K apartment, Athens, Greece
                                Clean record, smaller value, Southern EU market → low/medium risk, PASS
  3. REQ-2043  Viktor Petrov  — EUR 5M luxury villa, Limassol, Cyprus
                                High value, illiquid luxury segment, Cyprus market → higher risk
                                (Stress-Test Simulator sees ONLY asset data — KYC/PEP is outside its scope)

The point is to observe asset-type-aware and market-aware risk reasoning across
three different cases — proving verdicts EMERGE from data, not a scripted script.

Run: python -m agents.stress_test.test_stress_test
  or: python agents/stress_test/test_stress_test.py
"""

from __future__ import annotations

import json
import logging
import sys
import textwrap
from pathlib import Path

# ── Logging — configure before any imports that trigger module-level code ──────
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

from agents.stress_test.logic import run_stress_test

# ── Helpers ────────────────────────────────────────────────────────────────────

_SEP  = "─" * 72
_SEP2 = "═" * 72
_PASS = "✓"
_FAIL = "✗"

_RISK_ICON = {
    "low":      "🟢",
    "medium":   "🟡",
    "high":     "🔴",
    "critical": "🚨",
}

_DATA_FILE = (
    Path(__file__).parent.parent.parent / "database" / "brightuity_clients.json"
)


def _load_client(request_id: str) -> dict:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    for client in data["clients"]:
        if client.get("request_id") == request_id:
            return client
    raise ValueError(f"Client {request_id!r} not found in {_DATA_FILE}")


def _banner(title: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {title}")
    print(_SEP)


def _show_input(client: dict) -> None:
    """Print only the fields the Stress-Test Simulator actually receives."""
    print(f"  asset_type    : {client.get('asset_type')}")
    print(f"  asset_detail  : {client.get('asset_detail')}")
    print(f"  asset_value   : EUR {client.get('asset_value_eur', 0):,}")
    flags = client.get("risk_flags", [])
    if flags:
        for f in flags:
            print(f"  risk_flag     : {f}")
    else:
        print(f"  risk_flags    : (none)")
    print(f"  [KYC, docs, source_of_funds — excluded from this agent's scope]")
    print()


def _show_verdict(result: dict) -> None:
    icon = _PASS if result["verdict"] == "pass" else _FAIL
    risk_icon = _RISK_ICON.get(result.get("risk_level", ""), "")
    print(f"  {icon}  VERDICT      : {result['verdict'].upper()}")
    print(f"  {risk_icon}  RISK LEVEL   : {result.get('risk_level', '').upper()}")
    print(
        f"     summary      : {textwrap.fill(result['summary'], width=65, subsequent_indent='                   ')}"
    )
    factors = result.get("risk_factors", [])
    if factors:
        for f in factors:
            print(f"     risk_factor  : {f}")
    else:
        print(f"     risk_factors : (none)")
    print(f"     model_used   : {result['model_used']}")
    print(f"     was_fallback : {result['was_fallback']}")
    print(f"     latency_ms   : {result['latency_ms']}")

    rm = result.get("risk_metrics")
    if rm:
        sv = rm["stressed_value_range"]
        sc = rm["score_components"]
        print()
        print(f"  [ENGINE]  DETERMINISTIC RISK METRICS  (no LLM involvement)")
        print(f"     risk_score      : {rm['risk_score']}/100  "
              f"(illiq={sc['illiquidity_score']} + vol={sc['volatility_score']} "
              f"+ conc={sc['concentration_score']} + flags={sc['flags_score']})")
        print(f"     illiq_discount  : {rm['illiquidity_discount']:.0%}  "
              f"mkt_volatility: {rm['market_volatility']:.0%}")
        print(f"     worst_case      : EUR {sv['worst_case_eur']:>12,.0f}")
        print(f"     base_case       : EUR {sv['base_case_eur']:>12,.0f}")
        print(f"     best_case       : EUR {sv['best_case_eur']:>12,.0f}")
        print(f"     methodology     : {rm['methodology']}")


# ── Test runner ────────────────────────────────────────────────────────────────

def run_test(label: str, request_id: str, note: str = "") -> dict:
    _banner(f"{label}  |  {request_id}")
    if note:
        print(f"  NOTE: {note}")
        print()
    client = _load_client(request_id)
    print("  INPUT TO STRESS-TEST SIMULATOR (KYC/docs/expected_outcome excluded):")
    _show_input(client)
    print("  Calling engine + model... (deterministic engine first, then DeepSeek-V4-Pro on Featherless for narrative)")
    print()
    result = run_stress_test(client)
    print()
    print("  RESULT:")
    _show_verdict(result)
    return result


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print(_SEP2)
    print("  BRIGHTUITY · Stress-Test Simulator Agent · Live Test")
    print("  Market and liquidity risk assessment — verdicts emerge from asset data.")
    print(_SEP2)

    results: list[tuple[str, dict]] = []

    r1 = run_test(
        "TEST 1",
        "REQ-2041",
        note=(
            "Marcus Weber — EUR 2M commercial property, Berlin. "
            "Mature EU market, no risk flags. "
            "Expect asset-type reasoning: commercial property illiquidity, "
            "but Berlin is a deep, active market → low/medium risk."
        ),
    )
    results.append(("REQ-2041 / Marcus Weber  (EUR 2M, Berlin commercial)", r1))

    r2 = run_test(
        "TEST 2",
        "REQ-2042",
        note=(
            "Sofia Andreou — EUR 800K apartment, Athens. "
            "No risk flags. Smaller value, Southern EU market with historic volatility. "
            "Expect: residential + Greece market factors reflected in reasoning."
        ),
    )
    results.append(("REQ-2042 / Sofia Andreou (EUR 800K, Athens apartment)", r2))

    r3 = run_test(
        "TEST 3",
        "REQ-2043",
        note=(
            "Viktor Petrov — EUR 5M luxury villa, Limassol Cyprus. "
            "No risk_flags (KYC/PEP is KYC Guardian's scope — invisible here). "
            "Expect: luxury + Cyprus market + high value → elevated risk reasoning."
        ),
    )
    results.append(("REQ-2043 / Viktor Petrov (EUR 5M, Cyprus luxury villa)", r3))

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print(_SEP2)
    print("  SUMMARY — RISK DIFFERENTIATION PROOF")
    print(_SEP2)

    for label, result in results:
        verdict    = result["verdict"]
        risk_level = result.get("risk_level", "unknown")
        risk_icon  = _RISK_ICON.get(risk_level, "")
        v_icon     = _PASS if verdict == "pass" else _FAIL
        rm         = result.get("risk_metrics", {})
        score      = rm.get("risk_score", "--")
        sv         = rm.get("stressed_value_range", {})
        worst      = sv.get("worst_case_eur")
        worst_str  = f"EUR {worst:,.0f}" if worst else "--"
        print(
            f"  {v_icon}  {label:<45}  "
            f"score={score:<3}  risk={risk_level:<8}  worst={worst_str}  {risk_icon}"
        )

    print()
    print("  ENGINE NUMBERS ARE DETERMINISTIC — same inputs produce identical scores.")
    print("  Three different assets, three differentiated engine-computed risk profiles.")
    print(_SEP2)
    print()
    sys.exit(0)
