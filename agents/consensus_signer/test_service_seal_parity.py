"""
agents/consensus_signer/test_service_seal_parity.py
Brightuity — Byte-for-byte seal parity: in-process vs HTTP service.

Strategy:
  1. Generate ONE SECP256K1 private key for the test.
  2. Inject it into BOTH paths:
       (a) agents.orchestrator.core._signer  (used by seal_decision() in-process)
       (b) agents.consensus_signer.service._signer  (used by the FastAPI endpoint)
  3. Freeze datetime.now in logic.py so sealed_at is identical in both calls.
     (sealed_at is part of the canonical record that is hashed and signed.)
  4. Call path A (seal_decision, in-process) and path B (TestClient, HTTP boundary).
  5. Assert canonical_hash, signature, and public_key are byte-for-byte equal.

Why this works:
  RFC 6979 (deterministic k) guarantees that ECDSA over the same key + same message
  always produces the same signature bytes.  Freezing the timestamp ensures the
  canonical records (and therefore the messages) are identical across both paths.
  If even one byte differs the test fails — no other assertion is needed.

Run:
    pytest agents/consensus_signer/test_service_seal_parity.py -v
  or:
    python agents/consensus_signer/test_service_seal_parity.py
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from unittest.mock import patch, patch as mpatch

import pytest
from fastapi.testclient import TestClient

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import SECP256K1

from agents.consensus_signer.logic import ConsensusSigner
from agents.orchestrator.core import seal_decision
import agents.orchestrator.core as _core_module
import agents.consensus_signer.service as _service_module

# ── Fixed test data ───────────────────────────────────────────────────────────

_CASE_RECORD = {
    "request_id":      "REQ-PARITY-SVC-001",
    "client_id":       "CLT-PARITY-SVC",
    "asset_type":      "Commercial Property",
    "asset_value_eur": 1_500_000,
    "submitted_at":    "2026-01-01T00:00:00",
}

_AGENT_VERDICTS: dict = {
    "doc_auditor":        {"verdict": "pass", "summary": "All documents clean."},
    "kyc_guardian":       {"verdict": "pass", "summary": "KYC fully verified."},
    "dynamic_compliance": {"verdict": "pass", "summary": "MiCA Art. 17 compliant."},
    "stress_test":        {"verdict": "pass", "summary": "Risk score 18/100."},
    "asset_tokenizer":    {"verdict": "pass", "summary": "ERC-3643 structure approved."},
}

# Fixed timestamp so sealed_at is identical in both seal() calls.
_FIXED_DT  = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_STR = _FIXED_DT.isoformat(timespec="seconds")   # "2026-06-13T12:00:00+00:00"


# ── Key injection helper ──────────────────────────────────────────────────────

def _signer_with_key(private_key) -> ConsensusSigner:
    """Create a ConsensusSigner that uses a caller-supplied private key."""
    s = ConsensusSigner()
    s._private_key = private_key
    s._public_key  = private_key.public_key()
    return s


# ── Core parity test ──────────────────────────────────────────────────────────

def test_seal_parity_inprocess_vs_service():
    """
    Byte-for-byte equality: seal_decision() (in-process) vs POST /seal (service).

    The same SECP256K1 private key is injected into both paths.
    datetime.now is frozen so sealed_at — a field inside the signed canonical
    record — is identical.  RFC 6979 then guarantees identical ECDSA signatures.
    """
    # 1. One shared key for this test run.
    private_key = ec.generate_private_key(SECP256K1())

    orig_core_signer    = _core_module._signer
    orig_service_signer = _service_module._signer
    _core_module._signer    = _signer_with_key(private_key)
    _service_module._signer = _signer_with_key(private_key)

    try:
        # 2. Freeze datetime.now inside logic.py so sealed_at is identical.
        with patch("agents.consensus_signer.logic.datetime") as mock_dt:
            mock_dt.now.return_value = _FIXED_DT

            # 3a. Path A — in-process via seal_decision() with SIGNER_URL unset.
            with patch.dict(os.environ, {"SIGNER_URL": ""}, clear=False):
                result_a = seal_decision(_CASE_RECORD, _AGENT_VERDICTS)

            # 3b. Path B — HTTP boundary via the FastAPI service (same process).
            from agents.consensus_signer.service import app
            with TestClient(app) as client:
                resp = client.post(
                    "/seal",
                    json={
                        "case_record":    _CASE_RECORD,
                        "agent_verdicts": _AGENT_VERDICTS,
                    },
                )
    finally:
        _core_module._signer    = orig_core_signer
        _service_module._signer = orig_service_signer

    # 4. Both paths must produce SealedProof, not BlockedResult.
    assert result_a.get("status") == "sealed", (
        f"In-process path returned status={result_a.get('status')!r}: {result_a}"
    )
    assert resp.status_code == 200, f"Service /seal returned HTTP {resp.status_code}: {resp.text}"
    result_b = resp.json()
    assert result_b.get("status") == "sealed", (
        f"Service path returned status={result_b.get('status')!r}: {result_b}"
    )

    # 5. BYTE-FOR-BYTE equality on every cryptographic and structural field.
    assert result_a["canonical_hash"] == result_b["canonical_hash"], (
        "canonical_hash mismatch — the hashed bytes differ between paths:\n"
        f"  in-process: {result_a['canonical_hash']}\n"
        f"  service:    {result_b['canonical_hash']}"
    )
    assert result_a["signature"] == result_b["signature"], (
        "signature mismatch — RFC 6979 + same key + same message must give same sig:\n"
        f"  in-process: {result_a['signature'][:32]}...\n"
        f"  service:    {result_b['signature'][:32]}..."
    )
    assert result_a["public_key"] == result_b["public_key"], (
        "public_key mismatch — both paths must expose the same injected key:\n"
        f"  in-process: {result_a['public_key']}\n"
        f"  service:    {result_b['public_key']}"
    )
    assert result_a["sealed_at"] == result_b["sealed_at"] == _FIXED_STR, (
        f"sealed_at not frozen as expected:\n"
        f"  in-process: {result_a['sealed_at']}\n"
        f"  service:    {result_b['sealed_at']}\n"
        f"  expected:   {_FIXED_STR}"
    )
    assert result_a["curve"] == result_b["curve"] == "SECP256K1"
    assert result_a["gates_cleared"] == result_b["gates_cleared"]

    # 6. Both seals verify correctly with the returned public key.
    assert ConsensusSigner.verify(
        result_a["canonical_record"], result_a["signature"], result_a["public_key"]
    ), "In-process SealedProof failed ConsensusSigner.verify()"
    assert ConsensusSigner.verify(
        result_b["canonical_record"], result_b["signature"], result_b["public_key"]
    ), "Service SealedProof failed ConsensusSigner.verify()"


def test_service_health():
    """GET /health returns 200 with agent = consensus_signer."""
    from agents.consensus_signer.service import app
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agent"] == "consensus_signer"


def test_service_blocked_gate():
    """
    POST /seal with a KYC halt verdict returns a well-formed BlockedResult.
    The JSON must be serialisable and contain no signature field.
    """
    verdicts_with_halt = {**_AGENT_VERDICTS}
    verdicts_with_halt["kyc_guardian"] = {
        "verdict": "halt",
        "summary": "PEP match — hard halt.",
    }
    from agents.consensus_signer.service import app
    with TestClient(app) as client:
        resp = client.post(
            "/seal",
            json={"case_record": _CASE_RECORD, "agent_verdicts": verdicts_with_halt},
        )
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "blocked"
    assert result["failed_gate"] == "kyc_guardian"
    assert result["sealed_at"] is None
    assert "signature" not in result


def test_service_clean_import():
    """The service module imports cleanly and exposes the expected symbols."""
    from agents.consensus_signer.service import app, _signer, SealRequest
    assert app is not None
    assert isinstance(_signer, ConsensusSigner)
    assert SealRequest is not None


# ── Direct runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("═" * 70)
    print("  Consensus Signer — service parity test (byte-for-byte equality)")
    print("═" * 70)

    failures: list[str] = []
    tests = [
        ("seal parity: in-process vs service",   test_seal_parity_inprocess_vs_service),
        ("GET /health",                          test_service_health),
        ("POST /seal blocked gate",              test_service_blocked_gate),
        ("clean import",                         test_service_clean_import),
    ]
    for label, fn in tests:
        try:
            fn()
            print(f"  ✓  {label}")
        except Exception as exc:
            print(f"  ✗  FAIL: {label}")
            print(f"      {type(exc).__name__}: {exc}")
            failures.append(label)

    print()
    print("═" * 70)
    if not failures:
        print(f"  All {len(tests)} tests passed.")
    else:
        print(f"  {len(failures)}/{len(tests)} FAILED: {failures}")
    print("═" * 70)
    sys.exit(1 if failures else 0)
