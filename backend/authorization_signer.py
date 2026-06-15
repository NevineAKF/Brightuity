"""
backend/authorization_signer.py
Brightuity — Human Authorization Signer (Layer 2 integrity).

Two-layer integrity model:
  Layer 1 — Machine authority (agents/consensus_signer/logic.py):
    The ConsensusSigner produces an ECDSA seal over the AI analysis results
    (agent verdicts + gate outcome). It certifies that the machine analysis
    is unaltered. Ephemeral keypair per process instance.

  Layer 2 — Human authority (this module):
    The Head of Digital Assets signs the COMPLETE evidence package — including
    the Layer 1 machine seal and the human decision/rationale. It certifies
    that the human reviewed the package and recorded this decision. The signed
    payload is the union of machine + human authority.

    Tampering with ANY part of the evidence package (any agent verdict, any
    risk metric, the consensus hash, or the human rationale itself) after
    signing MUST cause verify_authorization() to return False.

Cryptographic design:
  Curve: SECP256K1 — same curve as the Layer 1 seal and the ERC-3643 token
    infrastructure. Consistent cryptographic story across the system.
  Algorithm: ECDSA with SHA-256. Same as ConsensusSigner for verifier
    compatibility — any party that can verify Layer 1 can verify Layer 2.
  Canonicalization: json.dumps(sort_keys=True, separators=(",",":"), UTF-8).
    Identical algorithm to ConsensusSigner._canonicalize(). The canonical
    form is byte-for-byte identical given the same logical content, making
    the proof independently verifiable without Brightuity's source code.

Signing protocol:
  1. Fill all human_authorization fields EXCEPT authorization_hash and
     authorization_signature (set those to "").
  2. Patch case_summary.final_decision with the decision value.
  3. Canonicalize the ENTIRE evidence package (all 8 sections, all fields).
  4. SHA-256 the canonical bytes.
  5. ECDSA sign the canonical bytes.
  6. Return the completed human_authorization block with the real hash and sig.

  Verification re-blanks hash+sig, re-canonicalizes, re-hashes, re-verifies.

Key custody:
  The private key is persisted to database/auth_private_key.pem so the public
  key is stable across server restarts (enabling verification of old packages).

  ╔══════════════════════════════════════════════════════════════════════════╗
  ║  PRODUCTION KEY CUSTODY — READ BEFORE DEPLOYMENT                        ║
  ╚══════════════════════════════════════════════════════════════════════════╝
  This demo persists a server-generated private key to disk. This is NOT
  acceptable for a production bank environment and does NOT constitute a
  qualified electronic signature under eIDAS or any equivalent regulation.

  In production, the Layer 2 signature MUST come from:
    • The reviewer's personal hardware credential (smartcard / FIDO2 token /
      HSM-backed personal key), OR
    • A bank HSM with dual-control access tied to the reviewer's identity.

  The private key MUST NEVER be a server-held key. Layer 2 authority is the
  HUMAN reviewer's authority — it must be cryptographically bound to a
  credential that only that human controls. A server key held by the bank
  infrastructure is machine authority, not human authority.

  The honest term for what this module produces is a
  "cryptographically-bound authorization record", not a qualified e-signature.
  Phase 2: signatory identity MUST come from the verified JWT session
  (auth.py), never from the request body.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
    SECP256K1,
)
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

# ── Curve (same as ConsensusSigner for verifier consistency) ──────────────────
_CURVE      = SECP256K1
_CURVE_NAME = "SECP256K1"

# ── Private key file (gitignored — never commit) ──────────────────────────────
# Override via AUTH_KEY_PATH env var (useful for tests or Docker secrets mount).
def _key_path() -> Path:
    default = str(
        Path(__file__).parent.parent / "database" / "auth_private_key.pem"
    )
    return Path(os.getenv("AUTH_KEY_PATH", default))


# ── Keypair management ────────────────────────────────────────────────────────

def _load_or_generate_keypair() -> tuple[EllipticCurvePrivateKey, EllipticCurvePublicKey]:
    """
    Load the demo authorization keypair from disk, generating it if absent.

    The same key is reused across restarts so previously signed packages
    remain verifiable. In production: remove this entirely and call the HSM.
    """
    path = _key_path()
    if path.exists():
        try:
            with open(path, "rb") as fh:
                priv = serialization.load_pem_private_key(fh.read(), password=None)
            return priv, priv.public_key()  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("auth_signer: could not load key from %s (%s) — regenerating", path, exc)

    priv = ec.generate_private_key(_CURVE())
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with open(path, "wb") as fh:
        fh.write(pem)
    logger.info("auth_signer: generated new demo keypair at %s", path)
    return priv, priv.public_key()


def _pub_hex(pub: EllipticCurvePublicKey) -> str:
    """Compressed SEC1 encoding, hex-encoded. 33 bytes for SECP256K1."""
    return pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint,
    ).hex()


# Module-level keypair (loaded once on first use via _get_keypair()).
_PRIVATE_KEY: EllipticCurvePrivateKey | None = None
_PUBLIC_KEY:  EllipticCurvePublicKey  | None = None


def _get_keypair() -> tuple[EllipticCurvePrivateKey, EllipticCurvePublicKey]:
    global _PRIVATE_KEY, _PUBLIC_KEY
    if _PRIVATE_KEY is None:
        _PRIVATE_KEY, _PUBLIC_KEY = _load_or_generate_keypair()
    return _PRIVATE_KEY, _PUBLIC_KEY  # type: ignore[return-value]


def reset_keypair_for_testing() -> None:
    """
    Discard the cached keypair so the next call to _get_keypair() reloads
    from disk. Called by tests that change AUTH_KEY_PATH mid-run.
    """
    global _PRIVATE_KEY, _PUBLIC_KEY
    _PRIVATE_KEY = None
    _PUBLIC_KEY  = None


# ── Canonicalization ──────────────────────────────────────────────────────────

def _canonicalize(obj: Any) -> bytes:
    """
    Identical algorithm to ConsensusSigner._canonicalize():
      • Keys sorted at every nesting level.
      • No whitespace between tokens.
      • UTF-8, no BOM.

    Two serialisations of the same logical dict always produce the same bytes,
    making the proof independently verifiable without access to this source.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ── Public interface ──────────────────────────────────────────────────────────

_BLANK = ""  # placeholder blanked into hash+sig fields before signing


def sign_authorization(
    evidence_package: dict[str, Any],
    decision: str,
    rationale: str,
    signatory_name: str,
    signatory_role: str,
    signed_at: str,
    annotations: list[str] | None = None,
) -> dict[str, Any]:
    """
    Sign the human authorization decision over the complete evidence package.

    Args:
        evidence_package: The stored EvidencePackage dict (human_authorization=None).
        decision:         "approved" or "rejected".
        rationale:        The reviewer's written justification.
        signatory_name:   Reviewer's name (from verified session in production).
        signatory_role:   Reviewer's role (e.g. "Head of Digital Assets").
        signed_at:        ISO 8601 UTC timestamp of the signing act.
        annotations:      Optional list of reviewer notes.

    Returns:
        Completed human_authorization block with:
          decision, decision_rationale, annotations, signatory_name,
          signatory_role, signed_at, authorization_hash (sha256:…),
          authorization_signature (hex DER ECDSA), public_key (hex),
          curve.

    Signing protocol (tamper-evidence guarantee):
      The signature covers the ENTIRE evidence package with the decision fields
      filled in but authorization_hash and authorization_signature blanked.
      Any post-signing mutation of any field causes verify_authorization() to
      return False.
    """
    priv, pub = _get_keypair()
    pub_hex = _pub_hex(pub)

    # Step 1 — Draft authorization block (hash + sig set to blank sentinel)
    draft_auth: dict[str, Any] = {
        "decision":                decision,
        "decision_rationale":      rationale,
        "annotations":             annotations or [],
        "signatory_name":          signatory_name,
        "signatory_role":          signatory_role,
        "signed_at":               signed_at,
        "authorization_hash":      _BLANK,   # ← blanked before canonicalization
        "authorization_signature": _BLANK,   # ← blanked before canonicalization
        "public_key":              pub_hex,
        "curve":                   _CURVE_NAME,
    }

    # Step 2 — Assemble signable package (deep copy — never mutate the caller's dict)
    signable = copy.deepcopy(evidence_package)
    signable["human_authorization"]          = draft_auth
    signable["case_summary"]["final_decision"] = decision

    # Step 3 — Canonicalize the entire 8-section package
    canonical_bytes = _canonicalize(signable)

    # Step 4 — SHA-256 digest (stored for audit display)
    sha256_hex = hashlib.sha256(canonical_bytes).hexdigest()

    # Step 5 — ECDSA sign (RFC 6979 deterministic k via `cryptography` library;
    #           sign() re-hashes internally with constant-time SHA-256 primitives)
    sig_der = priv.sign(canonical_bytes, ec.ECDSA(hashes.SHA256()))

    # Step 6 — Return the completed block
    return {
        "decision":                decision,
        "decision_rationale":      rationale,
        "annotations":             annotations or [],
        "signatory_name":          signatory_name,
        "signatory_role":          signatory_role,
        "signed_at":               signed_at,
        "authorization_hash":      f"sha256:{sha256_hex}",
        "authorization_signature": sig_der.hex(),
        "public_key":              pub_hex,
        "curve":                   _CURVE_NAME,
    }


def verify_authorization(evidence_package: dict[str, Any]) -> bool:
    """
    Verify the human authorization signature over a complete evidence package.

    Re-blanks authorization_hash and authorization_signature, re-canonicalizes
    the entire package, re-hashes, and verifies the ECDSA signature against
    the public_key stored in human_authorization.

    Returns:
        True  — signature is valid; the package is exactly as authorized.
        False — signature invalid, package was tampered with, or any input
                is malformed. Never raises — fail-safe default is False.

    Tamper examples that return False:
      • Any agent verdict changed from "pass" to another value.
      • Any risk_score, consensus_hash, or field in agent_evidence altered.
      • The decision or rationale text changed.
      • The signatory_name changed.
      • Any byte in the consensus seal modified.
    """
    try:
        auth = evidence_package.get("human_authorization")
        if not auth:
            return False

        sig_hex     = auth.get("authorization_signature", "")
        pub_hex_val = auth.get("public_key", "")
        if not sig_hex or not pub_hex_val:
            return False

        # Re-blank hash and signature before canonicalizing (same protocol as signing)
        verifiable = copy.deepcopy(evidence_package)
        verifiable["human_authorization"]["authorization_hash"]      = _BLANK
        verifiable["human_authorization"]["authorization_signature"] = _BLANK

        canonical_bytes = _canonicalize(verifiable)
        sig_bytes       = bytes.fromhex(sig_hex)
        pub_bytes       = bytes.fromhex(pub_hex_val)

        pub_key: EllipticCurvePublicKey = EllipticCurvePublicKey.from_encoded_point(
            _CURVE(), pub_bytes
        )
        pub_key.verify(sig_bytes, canonical_bytes, ec.ECDSA(hashes.SHA256()))
        return True

    except InvalidSignature:
        return False
    except Exception:
        return False
