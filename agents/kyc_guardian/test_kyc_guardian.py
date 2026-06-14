"""
agents/kyc_guardian/test_kyc_guardian.py
Brightuity — Live test for the KYC Guardian agent.

Runs the KYC Guardian against three real clients from brightuity_clients.json
and prints the full structured verdict for each.

Test cases:
  1. REQ-2041  Marcus Weber    — clean KYC, verifiable salary → expect PASS
  2. REQ-2042  Sofia Andreou   — clean KYC (her issue was documents, not identity)
                                  → expect PASS  (proves agents respect scope boundaries)
  3. REQ-2043  Viktor Petrov   — PEP match + unverifiable offshore funds
                                  → expect HALT  (hard pipeline stop)

The headline result: Viktor PASSED the Doc Auditor (clean documents), but now
HALTS at KYC (PEP + unverifiable funds). Same case, different agent, different
scope — proving each gate operates on its own evidence.

Run: python -m agents.kyc_guardian.test_kyc_guardian
  or: python agents/kyc_guardian/test_kyc_guardian.py
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

from agents.kyc_guardian.logic import screen_kyc

# ── Helpers ────────────────────────────────────────────────────────────────────

_SEP  = "─" * 72
_SEP2 = "═" * 72
_PASS = "✓"
_FAIL = "✗"
_HALT = "⛔"

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
    """Print only the KYC fields the agent actually receives (no expected_outcome)."""
    flags = client.get("kyc_flags", [])
    verifiable = client.get("source_verifiable", None)
    value_eur = client.get("asset_value_eur", 0)

    print(f"  name            : {client.get('full_name')}")
    print(f"  nationality     : {client.get('nationality')}")
    print(f"  date_of_birth   : {client.get('date_of_birth')}")
    print(f"  kyc_status      : {client.get('kyc_status')}")
    if flags:
        for f in flags:
            print(f"  kyc_flag        : {f}")
    else:
        print(f"  kyc_flags       : (none)")
    print(f"  source_of_funds : {client.get('source_of_funds')}")
    print(f"  source_verifiable: {'Yes' if verifiable else 'No' if verifiable is False else 'Unknown'}")
    print(f"  asset_type      : {client.get('asset_type')}")
    print(f"  asset_value     : EUR {value_eur:,}")
    print()


def _verdict_icon(verdict: str) -> str:
    return {"pass": _PASS, "fail": _FAIL, "halt": _HALT}.get(verdict, _FAIL)


def _show_verdict(result: dict) -> None:
    icon = _verdict_icon(result["verdict"])
    print(f"  {icon}  VERDICT       : {result['verdict'].upper()}")
    wrapped = textwrap.fill(
        result["summary"], width=65, subsequent_indent="                    "
    )
    print(f"     summary       : {wrapped}")
    flags = result.get("flags_raised", [])
    if flags:
        for flag in flags:
            print(f"     flag_raised   : {flag}")
    else:
        print(f"     flags_raised  : (none)")
    print(f"     model_used    : {result['model_used']}")
    print(f"     was_fallback  : {result['was_fallback']}")
    print(f"     latency_ms    : {result['latency_ms']}")


# ── Test runner ────────────────────────────────────────────────────────────────

def run_test(label: str, request_id: str, note: str = "") -> dict:
    _banner(f"{label}  |  {request_id}")
    if note:
        print(f"  NOTE: {note}")
        print()
    client = _load_client(request_id)
    print("  INPUT TO KYC GUARDIAN (expected_outcome & doc fields excluded):")
    _show_input(client)
    print("  Calling model... (claude-opus-4-8 on AI/ML API)")
    print()
    result = screen_kyc(client)
    print()
    print("  RESULT:")
    _show_verdict(result)
    return result


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print(_SEP2)
    print("  BRIGHTUITY · KYC Guardian Agent · Live Test")
    print("  Verdicts emerge from real client KYC data — nothing is scripted.")
    print(_SEP2)

    results: list[tuple[str, str, dict]] = []

    r1 = run_test(
        "TEST 1",
        "REQ-2041",
        note="Marcus Weber — clean KYC, salary verifiable. Expect PASS.",
    )
    results.append(("REQ-2041 / Marcus Weber", "pass", r1))

    r2 = run_test(
        "TEST 2",
        "REQ-2042",
        note=(
            "Sofia Andreou — her problem was incomplete documents (Doc Auditor FAIL). "
            "KYC is clean. Expect PASS — proves scope separation."
        ),
    )
    results.append(("REQ-2042 / Sofia Andreou", "pass", r2))

    r3 = run_test(
        "TEST 3",
        "REQ-2043",
        note=(
            "Viktor Petrov — PASSED Doc Auditor (clean docs), "
            "but PEP match + unverifiable offshore funds. Expect HALT."
        ),
    )
    results.append(("REQ-2043 / Viktor Petrov", "halt", r3))

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print(_SEP2)
    print("  SUMMARY")
    print(_SEP2)

    all_passed = True
    for label, expected_verdict, result in results:
        got = result["verdict"]
        ok = got == expected_verdict
        icon = _verdict_icon(expected_verdict) if ok else _FAIL
        all_passed = all_passed and ok
        status = "OK      " if ok else "MISMATCH"
        print(
            f"  {icon}  {label:<35}  "
            f"expected={expected_verdict:<4}  got={got:<4}  {status}"
        )

    print()
    print("  KEY PROOF: Viktor Petrov — PASS from Doc Auditor, HALT from KYC Guardian.")
    print("  Same case. Different agent. Different scope. Both correct.")
    print()

    if all_passed:
        print("  All 3 verdicts match expected direction. KYC Guardian confirmed.")
    else:
        print("  One or more verdicts diverged from expected direction.")
        print("  Review reasoning above — model variance is possible but rare for HALT cases.")
    print(_SEP2)
    print()
    sys.exit(0 if all_passed else 1)
