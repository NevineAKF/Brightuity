"""
agents/consensus_signer/logic.py
Brightuity — Consensus Signer (Agent 7 of 7)

═══════════════════════════════════════════════════════════════════════════════
SCOPE BOUNDARY — read before modifying
═══════════════════════════════════════════════════════════════════════════════
What this module DOES:
  1. Governance gate enforcement — iterates every mandatory agent gate and
     verifies its verdict equals "pass". If any gate is absent or non-passing,
     signing is unconditionally blocked and a structured BlockedResult is
     returned, naming the exact failed gate. There is no override path.

  2. Canonical record assembly — collects non-PII case metadata and the full
     set of agent verdicts into a single dict. PII (name, passport, DOB,
     address) is never included here — those fields remain in DB1 (Zone 1)
     and are accessed only by the agents that need them locally.

  3. Deterministic serialisation — the canonical record is serialised to bytes
     with sorted keys and fixed separators before any hashing or signing.
     See _canonicalize() for the full rationale.

  4. Integrity sealing — computes SHA-256 of the serialised record and produces
     an ECDSA signature, yielding a tamper-evident "Deterministic Gateway Proof".
     Every field of the canonical record is covered by the signature.

  5. Verification — given the canonical record, the hex signature, and the
     hex-encoded public key, confirms whether the record is exactly as it was
     at seal time. A single altered byte causes verification to return False.

─────────────────────────────────────────────────────────────────────────────
What this module DOES NOT DO, and CANNOT DO:
─────────────────────────────────────────────────────────────────────────────
  • It does NOT validate whether any agent's analysis is correct.
  • It does NOT detect model hallucinations or reasoning errors in the upstream
    LLM agents (Doc Auditor, KYC Guardian, Dynamic Compliance, Stress-Test
    Simulator, Asset Tokenizer).
  • It does NOT replace the human reviewer. The Head of Digital Assets must
    review the full report and make the final Approve/Reject decision.

  The Consensus Signer seals INTEGRITY, not CORRECTNESS.

  It guarantees that the set of verdicts recorded in the proof is exactly the
  set that was present at seal time, and that no field has been altered since.
  Whether those verdicts reflect accurate analysis is the responsibility of:
    (a) each agent's own anti-hallucination design (RAG, structured output
        contracts, dual-model fallback), and
    (b) the Head of Digital Assets exercising informed human judgement.

  This is the architectural answer to "how do you certify a non-deterministic
  system?" → Probabilistic intelligence analyses. Deterministic code seals.

Governance guarantee:
  No seal is possible unless ALL five mandatory gates return "pass".
  The governance check is a hard block. There is no override in this module.
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Final, Literal, TypedDict

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
    SECP256K1,
)


# ── Return types ───────────────────────────────────────────────────────────────

class SealedProof(TypedDict):
    """Returned by seal() when every mandatory gate cleared."""
    status: Literal["sealed"]
    request_id: str
    canonical_record: dict[str, Any]   # exact dict that was hashed and signed
    canonical_hash: str                # "sha256:<64-char hex>"
    signature: str                     # hex-encoded DER ECDSA signature
    public_key: str                    # hex-encoded compressed EC public key (33 B)
    sealed_at: str                     # ISO 8601 UTC (same value as in canonical_record)
    curve: str                         # e.g. "SECP256K1"
    gates_cleared: list[str]           # ordered list of the five gate names


class BlockedResult(TypedDict):
    """Returned by seal() when any mandatory gate is absent or non-passing."""
    status: Literal["blocked"]
    request_id: str
    failed_gate: str                   # name of the first gate that failed
    reason: str                        # human-readable explanation
    sealed_at: None                    # no seal was produced


SealResult = SealedProof | BlockedResult


# ── Constants ──────────────────────────────────────────────────────────────────

# The five LLM agents whose verdict must equal PASS_VERDICT before sealing.
# Listed in pipeline order. All are checked before producing any result.
MANDATORY_GATES: Final[tuple[str, ...]] = (
    "doc_auditor",
    "kyc_guardian",
    "dynamic_compliance",
    "stress_test",
    "asset_tokenizer",
)

PASS_VERDICT: Final[str] = "pass"

# ── Curve selection ────────────────────────────────────────────────────────────
# SECP256K1 — the Koblitz curve used by Bitcoin, Ethereum, and ERC-3643 token
# infrastructure. Using the same curve as the settlement layer creates a coherent
# cryptographic story and simplifies key-material interoperability.
#
# If your deployment requires FIPS 140-2 / 140-3 Level 3 compliance (e.g. for
# US federal procurement or DORA operational resilience mandates), substitute:
#   _CURVE      = ec.SECP384R1   (NIST P-384, NSA Suite B, 192-bit security)
#   _CURVE_NAME = "SECP384R1"
# The rest of this module is curve-agnostic — nothing else needs to change.
_CURVE: Final = SECP256K1
_CURVE_NAME: Final[str] = "SECP256K1"


# ── ConsensusSigner ────────────────────────────────────────────────────────────

class ConsensusSigner:
    """
    Deterministic final gate for the Brightuity compliance pipeline.

    One instance is created per process (typically by the Orchestrator) and
    reused across all cases handled in that session. The public key is stable
    for the lifetime of the instance; callers should persist it alongside
    every SealedProof they store.
    """

    def __init__(self) -> None:
        """
        Initialise with an ECDSA keypair.

        ╔══════════════════════════════════════════════════════════════╗
        ║  PRODUCTION KEY CUSTODY — MANDATORY READ FOR DEPLOYMENT     ║
        ╚══════════════════════════════════════════════════════════════╝
        In this build, an ephemeral keypair is generated in application
        memory for demonstration purposes. This is NEVER acceptable in a
        production bank environment.

        Production requirements:
          • The private key MUST reside inside a Hardware Security Module
            (e.g. AWS CloudHSM, Thales Luna Network HSM, nCipher nShield)
            or a dedicated software key vault (HashiCorp Vault Transit engine,
            Azure Key Vault Managed HSM, GCP Cloud HSM).
          • The private key MUST NEVER be exported, serialised to disk, logged,
            or present in application heap memory. The HSM performs signing
            in hardware; the application only sends the bytes to sign.
          • Access to the signing key must be subject to audit logging, role-
            based access control, and dual-control ceremony for key generation.
          • Key rotation policy and revocation procedures are compliance
            requirements under DORA Art. 9 and ISO 27001 A.10.
        """
        # ⚠ DEMO ONLY — ephemeral in-memory key. Replace with HSM call in production.
        self._private_key: EllipticCurvePrivateKey = ec.generate_private_key(_CURVE())
        self._public_key: EllipticCurvePublicKey = self._private_key.public_key()

    @property
    def public_key_hex(self) -> str:
        """
        Compressed SEC1 encoding of the public key, hex-encoded.
        33 bytes (02/03 prefix + 32-byte x-coordinate) for SECP256K1.
        Persist this alongside every SealedProof to enable future verification.
        """
        return self._public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        ).hex()

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _canonicalize(record: dict[str, Any]) -> bytes:
        """
        Produce a stable, deterministic byte representation of a dict.

        Rules applied:
          • Keys sorted alphabetically at every nesting level (sort_keys=True).
          • No whitespace between tokens (separators=(",", ":")).
          • UTF-8 encoded, no BOM, ensure_ascii=False (preserves Unicode names).

        Why this is non-negotiable:
          Python dicts preserve insertion order (CPython 3.7+), but callers,
          serialisers, or different Python runtimes can produce different
          orderings for the same logical record. A single key transposition
          produces different bytes → a different hash → a valid record fails
          verification even though nothing was altered.

          Sorted keys + fixed separators guarantee that two independent
          processes serialising the same logical record always produce
          identical bytes — making the proof independently verifiable by any
          party that holds the canonical_record and public key, without
          needing access to Brightuity's source code.
        """
        return json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _build_canonical_record(
        case_record: dict[str, Any],
        agent_verdicts: dict[str, dict[str, Any]],
        sealed_at: str,
    ) -> dict[str, Any]:
        """
        Assemble the dict that will be hashed and signed.

        Only non-PII fields are drawn from case_record. Sensitive identity
        data (full_name, passport_number, date_of_birth, address) stays in
        DB1 and is never included in the canonical record — it is handled
        locally by the agents that require it and must not cross Zone 1.

        The sealed_at timestamp is included inside the canonical record (not
        only in the envelope) so that the signing time is covered by the
        signature and cannot be altered post-hoc.
        """
        return {
            "agent_verdicts": agent_verdicts,
            "asset_type": case_record.get("asset_type"),
            "asset_value_eur": case_record.get("asset_value_eur"),
            "client_id": case_record.get("client_id"),
            "gates_cleared": list(MANDATORY_GATES),
            "request_id": case_record["request_id"],
            "schema_version": "1.0",
            "sealed_at": sealed_at,
            "sealed_by": "ConsensusSigner/1.0",
            "submitted_at": case_record.get("submitted_at"),
        }

    # ── Public interface ───────────────────────────────────────────────────────

    def seal(
        self,
        case_record: dict[str, Any],
        agent_verdicts: dict[str, dict[str, Any]],
    ) -> SealResult:
        """
        Enforce governance gates, then produce a tamper-evident proof.

        Args:
            case_record:    Non-PII case metadata from DB1. Must contain
                            "request_id". Optionally: "client_id",
                            "asset_type", "asset_value_eur", "submitted_at".
            agent_verdicts: Dict keyed by agent name. Each value must contain
                            at minimum {"verdict": str, "summary": str}.
                            Typically also includes "latency_ms".

        Returns:
            SealedProof   — if all five mandatory gates returned "pass".
                            Contains the canonical_record, SHA-256 hash, ECDSA
                            signature, and the public key needed to verify it.
            BlockedResult — if any gate is absent or non-passing.
                            Names the specific failed gate. No signature is
                            produced; no partial seal exists.
        """
        request_id: str = case_record["request_id"]

        # ── Hard governance gate check ─────────────────────────────────────────
        # Every gate is evaluated in pipeline order. The first failure returns
        # immediately. There is no partial seal, no bypass, no override.
        for gate in MANDATORY_GATES:
            gate_result = agent_verdicts.get(gate)

            if gate_result is None:
                return BlockedResult(
                    status="blocked",
                    request_id=request_id,
                    failed_gate=gate,
                    reason=(
                        f"Gate '{gate}' is absent from agent_verdicts. "
                        f"All {len(MANDATORY_GATES)} mandatory agents must "
                        f"report a verdict before sealing is possible."
                    ),
                    sealed_at=None,
                )

            verdict: str = gate_result.get("verdict", "")
            if verdict != PASS_VERDICT:
                summary: str = gate_result.get("summary", "(no summary provided)")
                return BlockedResult(
                    status="blocked",
                    request_id=request_id,
                    failed_gate=gate,
                    reason=(
                        f"Gate '{gate}' returned '{verdict}' "
                        f"(required: '{PASS_VERDICT}'). "
                        f"Agent summary: {summary}"
                    ),
                    sealed_at=None,
                )

        # ── Canonical record assembly ──────────────────────────────────────────
        sealed_at: str = datetime.now(timezone.utc).isoformat(timespec="seconds")
        canonical_record = ConsensusSigner._build_canonical_record(
            case_record, agent_verdicts, sealed_at
        )
        canonical_bytes: bytes = ConsensusSigner._canonicalize(canonical_record)

        # ── SHA-256 digest (for display and audit) ─────────────────────────────
        sha256_hex: str = hashlib.sha256(canonical_bytes).hexdigest()

        # ── ECDSA signature ────────────────────────────────────────────────────
        # We pass canonical_bytes (not the pre-computed digest) to sign().
        # The library re-hashes with SHA-256 internally using constant-time
        # primitives and generates the nonce via RFC 6979 (deterministic k),
        # which eliminates the risk of nonce reuse that would expose the
        # private key. The returned bytes are DER-encoded (ASN.1 SEQUENCE).
        signature_der: bytes = self._private_key.sign(
            canonical_bytes,
            ec.ECDSA(hashes.SHA256()),
        )

        return SealedProof(
            status="sealed",
            request_id=request_id,
            canonical_record=canonical_record,
            canonical_hash=f"sha256:{sha256_hex}",
            signature=signature_der.hex(),
            public_key=self.public_key_hex,
            sealed_at=sealed_at,
            curve=_CURVE_NAME,
            gates_cleared=list(MANDATORY_GATES),
        )

    @staticmethod
    def verify(
        canonical_record: dict[str, Any],
        signature_hex: str,
        public_key_hex: str,
    ) -> bool:
        """
        Verify that a canonical record has not been altered since sealing.

        Re-serialises the record with the same deterministic canonicalization
        used at seal time, then verifies the ECDSA signature. Any single-byte
        change to any field in canonical_record causes this to return False.

        Args:
            canonical_record: The dict stored in SealedProof["canonical_record"].
            signature_hex:    The hex string from SealedProof["signature"].
            public_key_hex:   The hex string from SealedProof["public_key"].

        Returns:
            True  — signature is valid; the record is exactly as sealed.
            False — signature is invalid, the record was tampered with, the
                    key is wrong, or any input is malformed.

        This method never raises. Any unexpected crypto or parsing error is
        treated as a verification failure (fail-safe default).
        """
        try:
            canonical_bytes: bytes = ConsensusSigner._canonicalize(canonical_record)
            signature_bytes: bytes = bytes.fromhex(signature_hex)
            pub_key_bytes: bytes = bytes.fromhex(public_key_hex)

            pub_key: EllipticCurvePublicKey = EllipticCurvePublicKey.from_encoded_point(
                _CURVE(), pub_key_bytes
            )
            # Raises InvalidSignature if the signature does not match.
            pub_key.verify(signature_bytes, canonical_bytes, ec.ECDSA(hashes.SHA256()))
            return True

        except InvalidSignature:
            return False
        except Exception:
            # Any malformed input (bad hex, invalid point, wrong curve) is a
            # verification failure — not an exception that should propagate.
            return False


# ── Self-test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Force UTF-8 output so box-drawing and checkmark characters render correctly
    # on any platform regardless of the terminal's default encoding.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    _SEP = "═" * 70

    def _pass(msg: str) -> None:
        print(f"  ✓  {msg}")

    def _fail(msg: str) -> None:
        print(f"  ✗  {msg}", file=sys.stderr)

    print(_SEP)
    print("  BRIGHTUITY · Consensus Signer · Self-Test")
    print(f"  Curve: {_CURVE_NAME}  |  Module: agents/consensus_signer/logic.py")
    print(_SEP)

    signer = ConsensusSigner()
    failures: int = 0

    # ── Test data ──────────────────────────────────────────────────────────────

    # Non-PII case metadata (what the Orchestrator would pass)
    _CASE_WEBER = {
        "request_id": "REQ-2041",
        "client_id": "CLT-0001",
        "asset_type": "Commercial Property",
        "asset_value_eur": 2_000_000,
        "submitted_at": "2026-06-09T13:29:00",
    }

    _CASE_PETROV = {
        "request_id": "REQ-2043",
        "client_id": "CLT-0003",
        "asset_type": "Luxury Villa",
        "asset_value_eur": 5_000_000,
        "submitted_at": "2026-06-11T06:11:00",
    }

    # Full-pass verdicts (Marcus Weber — expected: approve)
    _VERDICTS_ALL_PASS = {
        "doc_auditor": {
            "verdict": "pass",
            "summary": "All documents verified. Title deed clean, ownership chain complete.",
            "latency_ms": 1_240,
        },
        "kyc_guardian": {
            "verdict": "pass",
            "summary": "Identity verified. No PEP match. No sanctions hit. "
                       "Source of funds (salary accumulation) verified.",
            "latency_ms": 2_105,
        },
        "dynamic_compliance": {
            "verdict": "pass",
            "summary": "MiCA Art. 17 & 68 compliant. Jurisdiction: Germany (EU). "
                       "No cross-border restriction flags.",
            "latency_ms": 3_280,
        },
        "stress_test": {
            "verdict": "pass",
            "summary": "Risk score 23/100. Stress scenarios within policy limits: "
                       "downturn −18 %, rate shock −12 %, liquidity adequate.",
            "latency_ms": 1_870,
        },
        "asset_tokenizer": {
            "verdict": "pass",
            "summary": "ERC-3643 structure approved. 2,000 tokens @ €1,000. "
                       "Transfer restrictions: EU qualified investors only.",
            "latency_ms": 910,
        },
    }

    # Verdicts where KYC Guardian halts (Viktor Petrov — PEP match)
    _VERDICTS_KYC_HALT = {
        "doc_auditor": {
            "verdict": "pass",
            "summary": "Documents complete.",
            "latency_ms": 980,
        },
        "kyc_guardian": {
            "verdict": "halt",
            "summary": "PEP match — politically exposed network. "
                       "Source of funds: unverifiable offshore structures. "
                       "Hard halt — pipeline terminated.",
            "latency_ms": 1_650,
        },
        "dynamic_compliance": {
            "verdict": "pass",
            "summary": "Jurisdiction clear.",
            "latency_ms": 2_100,
        },
        "stress_test": {
            "verdict": "pass",
            "summary": "Risk score 31/100.",
            "latency_ms": 1_400,
        },
        "asset_tokenizer": {
            "verdict": "pass",
            "summary": "Token structure ready.",
            "latency_ms": 800,
        },
    }

    # ── TEST A: All gates clear → sealed ──────────────────────────────────────

    print()
    print("  [TEST A]  All five gates clear  (REQ-2041 · Marcus Weber)")
    print()

    result_a = signer.seal(_CASE_WEBER, _VERDICTS_ALL_PASS)

    print("  Gate verdicts:")
    for gate in MANDATORY_GATES:
        v = _VERDICTS_ALL_PASS[gate]["verdict"]
        print(f"    {gate:<22} → {v}")
    print()

    if result_a["status"] != "sealed":
        _fail(f"Expected status 'sealed', got '{result_a['status']}'")
        failures += 1
    else:
        _pass(f"Status       : {result_a['status']}")
        _pass(f"Canonical hash : {result_a['canonical_hash']}")
        sig_preview = result_a["signature"][:32] + "..."
        _pass(f"Signature    : {sig_preview}")
        pub_preview = result_a["public_key"][:16] + "..."
        _pass(f"Public key   : {pub_preview}")
        _pass(f"Curve        : {result_a['curve']}")
        _pass(f"Sealed at    : {result_a['sealed_at']}")

    # ── TEST B: Tamper detection ───────────────────────────────────────────────

    print()
    print("  [TEST B]  Tamper detection")
    print()

    # Verify the untampered proof first
    valid_original = ConsensusSigner.verify(
        result_a["canonical_record"],
        result_a["signature"],
        result_a["public_key"],
    )
    print(f"  Original record → verify() = {valid_original}")
    if not valid_original:
        _fail("Original record failed verification — unexpected")
        failures += 1
    else:
        _pass("Original record verifies correctly")

    # Alter one field and attempt to verify
    tampered_record: dict[str, Any] = dict(result_a["canonical_record"])
    original_value = tampered_record["asset_value_eur"]
    tampered_record["asset_value_eur"] = 9_999_999
    print()
    print(f"  Altering asset_value_eur: {original_value:,} → {tampered_record['asset_value_eur']:,}")

    valid_tampered = ConsensusSigner.verify(
        tampered_record,
        result_a["signature"],
        result_a["public_key"],
    )
    print(f"  Tampered record → verify() = {valid_tampered}")
    if valid_tampered:
        _fail("Tampered record passed verification — CRITICAL FAILURE")
        failures += 1
    else:
        _pass("Tamper correctly detected — verify() returned False")

    # ── TEST C: Governance gate blocked ───────────────────────────────────────

    print()
    print("  [TEST C]  Governance gate blocked  (REQ-2043 · Viktor Petrov)")
    print()

    result_c = signer.seal(_CASE_PETROV, _VERDICTS_KYC_HALT)

    kyc_verdict = _VERDICTS_KYC_HALT["kyc_guardian"]["verdict"]
    print(f"  kyc_guardian verdict : {kyc_verdict}")
    print()

    if result_c["status"] != "blocked":
        _fail(f"Expected status 'blocked', got '{result_c['status']}'")
        failures += 1
    else:
        _pass(f"Status       : {result_c['status']}")
        _pass(f"Failed gate  : {result_c['failed_gate']}")
        _pass(f"Reason       : {result_c['reason']}")
        _pass("No seal produced — governance guarantee holds")
        if "signature" in result_c:
            _fail("BlockedResult must not contain a signature — CRITICAL FAILURE")
            failures += 1

    # ── Summary ───────────────────────────────────────────────────────────────

    print()
    print(_SEP)
    if failures == 0:
        print("  3/3 self-tests passed.")
    else:
        print(f"  {failures} test(s) FAILED.", file=sys.stderr)
    print(_SEP)
    sys.exit(failures)
