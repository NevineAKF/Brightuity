"""
shared/pii_scopes.py
Auditable per-agent PII scope whitelist — the single source of truth.

AGENT_SCOPES is the authoritative registry of which client fields each
Band agent is permitted to receive from the PII data layer.  The gateway
(agents/pii_gateway/service.py) enforces these scopes at the HTTP boundary;
the test suite (shared/test_pii_scope_parity.py) asserts:
  (a) each scope matches the _*_FIELDS constant in the agent's logic.py, and
  (b) verdict logic produces byte-identical output for full vs scoped records.

Any scope change MUST be made here first, then reflected in the corresponding
_*_FIELDS constant in the agent's logic.py file simultaneously.

This module has NO project-level imports to prevent circular dependencies
(agents/* already imports from shared/*).
"""
from __future__ import annotations

AGENT_SCOPES: dict[str, frozenset[str]] = {
    "kyc_guardian": frozenset({
        "request_id",
        "full_name",
        "date_of_birth",
        "nationality",
        "kyc_status",
        "kyc_flags",
        "source_of_funds",
        "source_verifiable",
        "asset_value_eur",
        "asset_type",
    }),
    "dynamic_compliance": frozenset({
        "request_id",
        "full_name",
        "nationality",
        "asset_type",
        "asset_detail",
        "asset_value_eur",
        "source_of_funds",
        "source_verifiable",
    }),
    "doc_auditor": frozenset({
        "request_id",
        "encrypted_doc_id",
        "submitted_at",
        "full_name",
        "nationality",
        "asset_type",
        "asset_detail",
        "asset_value_eur",
        "documents_status",
        "document_issues",
    }),
    "stress_test": frozenset({
        "request_id",
        "asset_type",
        "asset_detail",
        "asset_value_eur",
        "risk_flags",
    }),
    "asset_tokenizer": frozenset({
        "request_id",
        "asset_type",
        "asset_detail",
        "asset_value_eur",
        "nationality",
    }),
}
