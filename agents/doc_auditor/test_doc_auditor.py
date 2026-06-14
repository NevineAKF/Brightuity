"""
agents/doc_auditor/test_doc_auditor.py
Brightuity — Live test for the Doc Auditor agent.

Runs the Doc Auditor against three real clients from brightuity_clients.json
and prints the full structured verdict for each.

Test cases:
  1. REQ-2041  Marcus Weber     — complete docs, no issues  → reasoning toward PASS
  2. REQ-2042  Sofia Andreou    — incomplete ownership chain → reasoning toward FAIL
  3. REQ-2043  Viktor Petrov    — complete docs (KYC issues are another agent's scope)
                                  → Doc Auditor reasoning toward PASS on docs alone
                                  (proves agents respect their scope boundary)

The point is to observe the model reasoning differently over different real data —
proving that verdicts EMERGE from the data, not from a hardcoded script.

Run: python -m agents.doc_auditor.test_doc_auditor
  or: python agents/doc_auditor/test_doc_auditor.py
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

from agents.doc_auditor.logic import audit_documents

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
    """Print only the fields the Doc Auditor actually receives (no expected_outcome)."""
    print(f"  name       : {client.get('full_name')}")
    print(f"  nationality: {client.get('nationality')}")
    print(f"  asset      : {client.get('asset_type')} — {client.get('asset_detail')}")
    print(f"  value      : EUR {client.get('asset_value_eur', 0):,}")
    print(f"  doc_status : {client.get('documents_status')}")
    issues = client.get("document_issues", [])
    if issues:
        for i in issues:
            print(f"  doc_issues : {i}")
    else:
        print(f"  doc_issues : (none)")
    print()


def _show_verdict(result: dict) -> None:
    icon = _PASS if result["verdict"] == "pass" else _FAIL
    print(f"  {icon}  VERDICT      : {result['verdict'].upper()}")
    print(f"     summary      : {textwrap.fill(result['summary'], width=65, subsequent_indent='                   ')}")
    if result["issues_found"]:
        for issue in result["issues_found"]:
            print(f"     issue        : {issue}")
    else:
        print(f"     issues_found : (none)")
    print(f"     model_used   : {result['model_used']}")
    print(f"     was_fallback : {result['was_fallback']}")
    print(f"     latency_ms   : {result['latency_ms']}")


# ── Test runner ────────────────────────────────────────────────────────────────

def run_test(label: str, request_id: str, note: str = "") -> dict:
    _banner(f"{label}  |  {request_id}")
    if note:
        print(f"  NOTE: {note}")
        print()
    client = _load_client(request_id)
    print("  INPUT TO DOC AUDITOR (expected_outcome deliberately excluded):")
    _show_input(client)
    print("  Calling model... (Qwen/Qwen3.6-27B on Featherless)")
    print()
    result = audit_documents(client)
    print()
    print("  RESULT:")
    _show_verdict(result)
    return result


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print(_SEP2)
    print("  BRIGHTUITY · Doc Auditor Agent · Live Test")
    print("  Verdicts emerge from real client data — nothing is scripted.")
    print(_SEP2)

    results: list[tuple[str, str, dict]] = []

    r1 = run_test(
        "TEST 1",
        "REQ-2041",
        note="Marcus Weber — complete docs, no flags. Expect the model to reason toward PASS.",
    )
    results.append(("REQ-2041 / Marcus Weber", "pass", r1))

    r2 = run_test(
        "TEST 2",
        "REQ-2042",
        note="Sofia Andreou — ownership chain incomplete. Expect the model to reason toward FAIL.",
    )
    results.append(("REQ-2042 / Sofia Andreou", "fail", r2))

    r3 = run_test(
        "TEST 3",
        "REQ-2043",
        note=(
            "Viktor Petrov — complete docs (KYC/PEP issues exist, but that is KYC Guardian's scope). "
            "Doc Auditor must reason on documents only → expect PASS."
        ),
    )
    results.append(("REQ-2043 / Viktor Petrov", "pass", r3))

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print(_SEP2)
    print("  SUMMARY")
    print(_SEP2)

    all_passed = True
    for label, expected_verdict, result in results:
        got = result["verdict"]
        ok = got == expected_verdict
        icon = _PASS if ok else _FAIL
        all_passed = all_passed and ok
        status = "OK  " if ok else "MISMATCH"
        print(
            f"  {icon}  {label:<35}  "
            f"expected={expected_verdict:<4}  got={got:<4}  {status}"
        )

    print()
    if all_passed:
        print("  All 3 verdicts match expected direction. Agent reasoning confirmed.")
    else:
        print("  One or more verdicts diverged from expected direction.")
        print("  This may be model variance — review the reasoning above.")
        print("  Expected direction is a guide, not a hardcoded assertion.")
    print(_SEP2)
    print()
    sys.exit(0 if all_passed else 1)
