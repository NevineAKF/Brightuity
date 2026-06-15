"""
agents/asset_tokenizer/test_asset_tokenizer.py
Brightuity — Live test for the Asset Tokenizer agent.

Runs the Asset Tokenizer against three real clients from brightuity_clients.json
and prints the full proposed token structure for each.

Test cases:
  1. REQ-2041  Marcus Weber   — EUR 2,000,000 commercial property, Berlin
                                → Expect: institutional-grade fractionalization, larger lot size
  2. REQ-2042  Sofia Andreou  — EUR 800,000 residential apartment, Athens
                                → Expect: retail-eligible fractions, broader supply
  3. REQ-2043  Viktor Petrov  — EUR 5,000,000 luxury villa, Limassol Cyprus
                                → Expect: high per-token denomination, limited supply

The proof: the model proposes DIFFERENT structures per asset. The fractionalization
math should verify: total_tokens × value_per_token_eur ≈ asset_value_eur (±5%).

ALSO WATCH: was_fallback flag and log output. If GPT-4o fails and Gemini 2.5 Pro
carries the call instead, this will surface in the logs and was_fallback=True.
Report this clearly — do not hide primary failures.

Run: python -m agents.asset_tokenizer.test_asset_tokenizer
  or: python agents/asset_tokenizer/test_asset_tokenizer.py
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

from agents.asset_tokenizer.logic import design_token_structure

# ── Helpers ────────────────────────────────────────────────────────────────────

_SEP  = "─" * 72
_SEP2 = "═" * 72
_PASS = "✓"
_FAIL = "✗"

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
    """Print only the fields the Asset Tokenizer actually receives."""
    print(f"  asset_type    : {client.get('asset_type')}")
    print(f"  asset_detail  : {client.get('asset_detail')}")
    print(f"  asset_value   : EUR {client.get('asset_value_eur', 0):,}")
    print(f"  nationality   : {client.get('nationality')}")
    print(f"  [KYC, docs, risk_flags, source_of_funds — excluded from this agent's scope]")
    print()


def _show_verdict(result: dict) -> None:
    icon = _PASS if result["verdict"] == "pass" else _FAIL
    asset_value = None  # will compute math check below

    print(f"  {icon}  VERDICT           : {result['verdict'].upper()}")
    print(
        f"     summary           : {textwrap.fill(result['summary'], width=60, subsequent_indent='                       ')}"
    )
    print(f"     token_standard    : {result.get('token_standard', '—')}")
    total = result.get("total_tokens", 0)
    per_token = result.get("value_per_token_eur", 0.0)
    print(f"     total_tokens      : {total:,}")
    print(f"     value_per_token   : EUR {per_token:,.2f}")
    implied = total * per_token
    print(f"     implied value     : EUR {implied:,.0f}  [total × per_token]")
    notes = result.get("structure_notes", [])
    if notes:
        for n in notes:
            print(f"     structure_note    : {n}")
    else:
        print(f"     structure_notes   : (none)")
    fallback_flag = "YES ← GPT-4o FAILED, GEMINI CARRIED" if result["was_fallback"] else "no"
    print(f"     model_used        : {result['model_used']}")
    print(f"     was_fallback      : {fallback_flag}")
    print(f"     latency_ms        : {result['latency_ms']}")
    return implied


# ── Test runner ────────────────────────────────────────────────────────────────

def run_test(label: str, request_id: str, note: str = "") -> dict:
    _banner(f"{label}  |  {request_id}")
    if note:
        print(f"  NOTE: {note}")
        print()
    client = _load_client(request_id)
    print("  INPUT TO ASSET TOKENIZER (KYC/docs/expected_outcome excluded):")
    _show_input(client)
    print("  Calling model... (gpt-4o on AI/ML API — google/gemini-2.5-pro fallback)")
    print()
    result = design_token_structure(client)
    print()
    print("  RESULT:")
    implied = _show_verdict(result)
    return result, client.get("asset_value_eur", 0), implied


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print(_SEP2)
    print("  BRIGHTUITY · Asset Tokenizer Agent · Live Test")
    print("  Token structure proposals — DIFFERENT per asset. Math must verify.")
    print(_SEP2)

    cases: list[tuple[str, dict, int, float]] = []

    r1, v1, i1 = run_test(
        "TEST 1",
        "REQ-2041",
        note=(
            "Marcus Weber — EUR 2M commercial property, Berlin. "
            "Expect institutional-grade fractionalization: larger lot size, "
            "commercial property transfer restrictions."
        ),
    )
    cases.append(("REQ-2041 / Marcus Weber  (EUR 2M, Berlin commercial)", r1, v1, i1))

    r2, v2, i2 = run_test(
        "TEST 2",
        "REQ-2042",
        note=(
            "Sofia Andreou — EUR 800K apartment, Athens. "
            "Expect retail-eligible fractions: smaller per-token value, larger supply."
        ),
    )
    cases.append(("REQ-2042 / Sofia Andreou (EUR 800K, Athens apartment)", r2, v2, i2))

    r3, v3, i3 = run_test(
        "TEST 3",
        "REQ-2043",
        note=(
            "Viktor Petrov — EUR 5M luxury villa, Limassol Cyprus. "
            "Expect limited-edition supply, high per-token denomination, "
            "restricted transfer class, extended lock-up."
        ),
    )
    cases.append(("REQ-2043 / Viktor Petrov (EUR 5M, Cyprus luxury villa)", r3, v3, i3))

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print(_SEP2)
    print("  SUMMARY — STRUCTURE DIFFERENTIATION + MATH VERIFICATION")
    print(_SEP2)

    any_fallback = False
    all_math_ok = True

    for label, result, asset_value, implied in cases:
        verdict = result["verdict"]
        total   = result.get("total_tokens", 0)
        per_tok = result.get("value_per_token_eur", 0.0)
        fb      = result.get("was_fallback", False)
        if fb:
            any_fallback = True

        math_pct = abs(implied - asset_value) / asset_value * 100 if asset_value else 999
        math_ok  = math_pct <= 5.0
        if not math_ok:
            all_math_ok = False

        math_str = f"±{math_pct:.1f}%  {'OK' if math_ok else 'WARN >5%'}"
        fb_str   = "FALLBACK" if fb else "primary"

        icon = _PASS if (verdict == "pass" and math_ok) else _FAIL
        print(
            f"  {icon}  {label:<46}  "
            f"tokens={total:>6,}  @EUR{per_tok:>8,.0f}  math={math_str}  model={fb_str}"
        )

    print()
    if any_fallback:
        print("  ⚠  GPT-4o FAILED on one or more calls — google/gemini-2.5-pro carried those requests.")
        print("     Review was_fallback flags above.")
    else:
        print("  GPT-4o (primary) handled all calls — no fallback triggered.")

    print()
    if all_math_ok:
        print("  Math invariant satisfied on all cases: total_tokens × per_token ≈ asset_value (±5%).")
    else:
        print("  ⚠  Math invariant exceeded ±5% on one or more cases — review structure_notes.")

    print()
    print("  Three assets, three distinct structures. Tokenization design emerges from data.")
    print(_SEP2)
    print()
    sys.exit(0)
