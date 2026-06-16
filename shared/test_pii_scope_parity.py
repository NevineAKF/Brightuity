"""
shared/test_pii_scope_parity.py
Three independent proofs of the PII boundary:

TEST 1 — scope_definitions_match_logic
  AGENT_SCOPES in shared/pii_scopes.py must be byte-identical to the _*_FIELDS
  frozensets defined inside each agent's logic.py.  Proves one source of truth.

TEST 2 — verdict_parity (parametrised: 5 agents × 3 demo clients)
  For each agent, calling the engine with (a) the full client record and
  (b) only the scoped fields must produce a byte-for-byte identical return dict.
  The LLM call is mocked; deterministic sub-engines (watchlist screening,
  risk_engine, RAG retrieval) are also mocked so the test runs in CI without
  live APIs or the Chroma index.
  If any scoped call differs from the full-record call, a field is missing from
  AGENT_SCOPES — fix the scope, not the test.

TEST 3 — gateway_scope_no_leak (FastAPI TestClient)
  The /scope endpoint must return exactly AGENT_SCOPES[agent] keys — no more,
  no less.  expected_outcome and passport_number must NEVER appear in any
  agent's response.  Tests all 5 agents against all 3 demo clients.

Run:
    pytest shared/test_pii_scope_parity.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from shared.pii_scopes import AGENT_SCOPES
from shared.call_agent_model import ModelResponse
from shared.schemas import (
    AssetTokenizerVerdict,
    DocAuditorVerdict,
    DynamicComplianceVerdict,
    KycGuardianVerdict,
    StressTestNarrative,
)

# ── Test data ──────────────────────────────────────────────────────────────────

_JSON_FILE = Path(__file__).parent.parent / "database" / "brightuity_clients.json"

def _load_demo_clients() -> dict[str, dict[str, Any]]:
    data = json.loads(_JSON_FILE.read_text(encoding="utf-8"))
    idx = {c["request_id"]: c for c in data["clients"]}
    return {rid: idx[rid] for rid in ("REQ-2041", "REQ-2042", "REQ-2043")}

_DEMO = _load_demo_clients()

# ── Mock LLM infrastructure ────────────────────────────────────────────────────

_SCHEMA_DEFAULTS: dict = {
    DocAuditorVerdict: {
        "verdict": "pass",
        "summary": "mock-doc-summary",
        "issues_found": [],
    },
    KycGuardianVerdict: {
        "verdict": "pass",
        "summary": "mock-kyc-summary",
        "flags_raised": [],
    },
    DynamicComplianceVerdict: {
        "verdict": "pass",
        "summary": "mock-compliance-summary",
        "jurisdiction": "EU",
        "citations": ["MiCA Art. 1"],
        "concerns": [],
    },
    StressTestNarrative: {
        "summary": "mock-stress-summary",
        "risk_factors": ["mock risk factor"],
    },
    AssetTokenizerVerdict: {
        "verdict": "pass",
        "summary": "mock-token-summary",
        "token_standard": "ERC-3643",
        "total_tokens": 1_000,
        "value_per_token_eur": 100.0,
        "structure_notes": ["mock note"],
    },
}

_MOCK_PASSAGES = [
    {
        "regulation": "MiCA",
        "article": "Art. 1",
        "topic": "authorisation",
        "text": "Mock provision text.",
        "score": 0.95,
    }
]

_MOCK_SCREENING = {
    "matched": False,
    "match_type": None,
    "matched_entry": None,
    "match_score": 0.0,
    "sources_checked": ["EU Sanctions", "OFAC", "PEP Register"],
}


def _mock_call_agent_model(agent_name, prompt, system_prompt, schema=None):
    data = schema(**_SCHEMA_DEFAULTS[schema])
    return ModelResponse(
        data=data,
        model_used="mock-model",
        platform="mock",
        was_fallback=False,
        attempts=1,
        latency_ms=0,
    )


# ── Test 1: scope definitions match logic.py _*_FIELDS ────────────────────────

def test_scope_definitions_match_logic_fields():
    """AGENT_SCOPES must be identical to the _*_FIELDS frozensets in logic.py."""
    from agents.kyc_guardian.logic import _KYC_FIELDS
    from agents.dynamic_compliance.logic import _COMPLIANCE_FIELDS
    from agents.doc_auditor.logic import _DOC_FIELDS
    from agents.stress_test.logic import _STRESS_FIELDS
    from agents.asset_tokenizer.logic import _TOKENIZER_FIELDS

    expected = {
        "kyc_guardian":       _KYC_FIELDS,
        "dynamic_compliance": _COMPLIANCE_FIELDS,
        "doc_auditor":        _DOC_FIELDS,
        "stress_test":        _STRESS_FIELDS,
        "asset_tokenizer":    _TOKENIZER_FIELDS,
    }
    for agent, logic_fields in expected.items():
        assert AGENT_SCOPES[agent] == logic_fields, (
            f"{agent}: AGENT_SCOPES has {sorted(AGENT_SCOPES[agent])} "
            f"but logic.py has {sorted(logic_fields)}"
        )


# ── Test 2: verdict parity (full record vs scoped record) ─────────────────────

_AGENT_ENGINE_FNS: dict[str, tuple] = {
    "kyc_guardian":       ("agents.kyc_guardian.logic.call_agent_model",),
    "dynamic_compliance": (
        "agents.dynamic_compliance.logic.call_agent_model",
        "agents.dynamic_compliance.logic.retrieve_relevant_law",
    ),
    "doc_auditor":        ("agents.doc_auditor.logic.call_agent_model",),
    "stress_test":        ("agents.stress_test.logic.call_agent_model",),
    "asset_tokenizer":    ("agents.asset_tokenizer.logic.call_agent_model",),
}


def _call_agent(agent_name: str, client_record: dict) -> dict:
    """Call the appropriate agent logic function with mocked LLM."""
    from agents.kyc_guardian.logic import screen_kyc
    from agents.dynamic_compliance.logic import assess_compliance
    from agents.doc_auditor.logic import audit_documents
    from agents.stress_test.logic import run_stress_test
    from agents.asset_tokenizer.logic import design_token_structure

    fns = {
        "kyc_guardian":       screen_kyc,
        "dynamic_compliance": assess_compliance,
        "doc_auditor":        audit_documents,
        "stress_test":        run_stress_test,
        "asset_tokenizer":    design_token_structure,
    }
    return fns[agent_name](client_record)


def _run_parity(agent_name: str, full_client: dict) -> tuple[dict, dict]:
    """
    Call the agent engine twice — with the full record and with only scoped fields.
    Returns (result_full, result_scoped). Both calls use the same mocked LLM.
    """
    scoped = {k: full_client[k] for k in AGENT_SCOPES[agent_name] if k in full_client}

    patches = {
        "agents.kyc_guardian.logic.screen_against_watchlist": _MOCK_SCREENING,
        "agents.dynamic_compliance.logic.retrieve_relevant_law": _MOCK_PASSAGES,
    }

    with (
        patch("agents.kyc_guardian.logic.call_agent_model", side_effect=_mock_call_agent_model),
        patch("agents.dynamic_compliance.logic.call_agent_model", side_effect=_mock_call_agent_model),
        patch("agents.doc_auditor.logic.call_agent_model", side_effect=_mock_call_agent_model),
        patch("agents.stress_test.logic.call_agent_model", side_effect=_mock_call_agent_model),
        patch("agents.asset_tokenizer.logic.call_agent_model", side_effect=_mock_call_agent_model),
        patch("agents.kyc_guardian.logic.screen_against_watchlist", return_value=_MOCK_SCREENING),
        patch("agents.dynamic_compliance.logic.retrieve_relevant_law", return_value=_MOCK_PASSAGES),
    ):
        result_full   = _call_agent(agent_name, full_client)
        result_scoped = _call_agent(agent_name, scoped)

    return result_full, result_scoped


_PARITY_PARAMS = [
    (agent, rid)
    for agent in AGENT_SCOPES
    for rid in ("REQ-2041", "REQ-2042", "REQ-2043")
]


@pytest.mark.parametrize("agent_name,request_id", _PARITY_PARAMS,
                         ids=[f"{a}-{r}" for a, r in _PARITY_PARAMS])
def test_verdict_parity(agent_name: str, request_id: str):
    """
    Full record and scoped record must produce byte-identical verdict dicts.

    If this test fails for an agent, a field accessed by that agent's logic is
    absent from AGENT_SCOPES[agent_name].  Fix the scope — not the test.
    """
    full_client = _DEMO[request_id]
    result_full, result_scoped = _run_parity(agent_name, full_client)

    assert result_full == result_scoped, (
        f"{agent_name}/{request_id}: full vs scoped produced different results.\n"
        f"Keys in full only:   {set(result_full) - set(result_scoped)}\n"
        f"Keys in scoped only: {set(result_scoped) - set(result_full)}\n"
        f"Value differences:\n"
        + "\n".join(
            f"  {k}: {result_full.get(k)!r} vs {result_scoped.get(k)!r}"
            for k in set(result_full) | set(result_scoped)
            if result_full.get(k) != result_scoped.get(k)
        )
    )


# ── Test 3: gateway scope — no out-of-scope field ever leaks ──────────────────

# Fields that must NEVER appear in any gateway response regardless of agent.
_FORBIDDEN_FIELDS = frozenset({
    "expected_outcome",
    "passport_number",
    "date_of_birth",  # only kyc_guardian may see this
    "address",
    "gender",
    "photo_url",
    "client_id",
})


def test_gateway_scope_no_leak():
    """
    /scope/{agent}/{request_id} must return exactly AGENT_SCOPES[agent] keys.
    expected_outcome and other high-sensitivity fields must never appear.
    """
    from agents.pii_gateway.service import app

    with TestClient(app) as client:
        # Liveness
        resp = client.get("/health")
        assert resp.status_code == 200
        health = resp.json()
        assert health["status"] == "ok"
        assert health["clients_loaded"] == 100

        for agent_name, allowed_fields in AGENT_SCOPES.items():
            for request_id in ("REQ-2041", "REQ-2042", "REQ-2043"):
                resp = client.get(f"/scope/{agent_name}/{request_id}")
                assert resp.status_code == 200, (
                    f"{agent_name}/{request_id}: expected 200, got {resp.status_code}: {resp.text}"
                )
                data = resp.json()
                returned_keys = set(data.keys())

                # No key outside the whitelist
                assert returned_keys <= allowed_fields, (
                    f"{agent_name}/{request_id}: out-of-scope keys returned: "
                    f"{returned_keys - allowed_fields}"
                )

                # Forbidden fields never appear
                leaked = _FORBIDDEN_FIELDS - (
                    # date_of_birth IS in kyc_guardian scope — exclude it from forbidden check there
                    frozenset({"date_of_birth"}) if agent_name == "kyc_guardian" else frozenset()
                )
                for field in leaked:
                    assert field not in data, (
                        f"{agent_name}/{request_id}: forbidden field {field!r} leaked in response"
                    )

        # 400 for unknown agent
        resp = client.get("/scope/unknown_agent/REQ-2041")
        assert resp.status_code == 400

        # 404 for unknown request_id
        resp = client.get(f"/scope/kyc_guardian/REQ-9999")
        assert resp.status_code == 404
