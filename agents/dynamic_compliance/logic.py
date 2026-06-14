"""
agents/dynamic_compliance/logic.py
Brightuity — Dynamic Compliance agent.

Maps each RWA tokenisation case to its regulatory jurisdiction and issues a
legal compliance opinion grounded exclusively in retrieved regulatory text.
This is the anti-hallucination design: the model is given ONLY the provisions
retrieved for this specific case and must cite their article numbers. It may
not rely on legal knowledge outside the retrieved passages.

Framework: retrieval-augmented generation (RAG).
  1. Build a targeted retrieval query from the case facts.
  2. Retrieve the top-k most relevant provisions from the ChromaDB corpus.
  3. Inject the retrieved provisions (with article numbers) into the prompt.
  4. Instruct the model to ground every conclusion in the retrieved text.
  5. The engine returns a validated DynamicComplianceVerdict — citations prove
     the opinion is grounded in retrieved law, not hallucinated.

Public interface:
    assess_compliance(client_record: dict) -> dict
"""

from __future__ import annotations

import logging
from pathlib import Path

from agents.dynamic_compliance.retrieval import retrieve_relevant_law
from shared.call_agent_model import ModelUnavailableError, call_agent_model
from shared.schemas import DynamicComplianceVerdict

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Fields this agent reads from the client record.
# KYC fields, document fields, risk_flags, and expected_outcome are excluded.
_COMPLIANCE_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "full_name",
    "nationality",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "source_of_funds",
    "source_verifiable",
})

_EU_MEMBER_STATES: frozenset[str] = frozenset({
    "Germany", "France", "Italy", "Spain", "Netherlands", "Belgium",
    "Austria", "Portugal", "Greece", "Cyprus", "Luxembourg", "Ireland",
    "Denmark", "Sweden", "Finland", "Poland", "Czech Republic", "Hungary",
    "Romania", "Bulgaria", "Croatia", "Slovakia", "Slovenia", "Estonia",
    "Latvia", "Lithuania", "Malta",
})

_RETRIEVAL_K = 6


# ── Jurisdiction mapping ───────────────────────────────────────────────────────

def _map_jurisdiction(nationality: str) -> str:
    if nationality in _EU_MEMBER_STATES:
        return "EU"
    return "EU"  # Meridian Digital Bank is EU-incorporated; default to EU framework


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _build_retrieval_query(
    asset_type: str,
    asset_value_eur: int | float,
    source_of_funds: str,
    jurisdiction: str,
) -> str:
    return (
        f"What are the regulatory authorisation and compliance requirements for "
        f"tokenising {asset_type} valued at EUR {asset_value_eur:,} under {jurisdiction} law? "
        f"What MiCA authorisation, ART classification, white paper, and reserve obligations apply? "
        f"Source of funds: {source_of_funds}. "
        f"What AMLD customer due diligence, source-of-funds verification, and "
        f"enhanced due diligence requirements apply to this transaction?"
    )


# ── Prompt construction ────────────────────────────────────────────────────────

def _format_passages(passages: list[dict]) -> str:
    lines: list[str] = []
    for i, p in enumerate(passages, 1):
        lines.append(
            f"[{i}] {p['regulation']} | {p['article']}\n"
            f"    Topic: {p['topic']}\n"
            f"    {p['text']}"
        )
    return "\n\n".join(lines)


def _build_prompt(client_record: dict, passages: list[dict], jurisdiction: str) -> str:
    """
    Build the user-turn prompt containing case facts + retrieved legal provisions.
    expected_outcome and KYC/doc/risk fields are never referenced here.
    """
    r = client_record
    verifiable = r.get("source_verifiable", None)
    verifiable_display = (
        "Yes" if verifiable is True
        else "No" if verifiable is False
        else "Unknown"
    )
    value_eur = r.get("asset_value_eur", 0)
    try:
        value_display = f"EUR {value_eur:,}"
    except (TypeError, ValueError):
        value_display = f"EUR {value_eur}"

    case_block = (
        "CASE FACTS\n"
        f"  Request ID       : {r.get('request_id', 'UNKNOWN')}\n"
        f"  Applicant        : {r.get('full_name', 'UNKNOWN')} ({r.get('nationality', 'UNKNOWN')})\n"
        f"  Jurisdiction     : {jurisdiction} (MiCA + AMLD apply)\n"
        f"  Asset Type       : {r.get('asset_type', 'UNKNOWN')}\n"
        f"  Asset Detail     : {r.get('asset_detail', 'UNKNOWN')}\n"
        f"  Stated Value     : {value_display}\n"
        f"  Source of Funds  : {r.get('source_of_funds', 'UNKNOWN')} "
        f"(Verifiable: {verifiable_display})"
    )

    provisions_block = (
        "RETRIEVED LEGAL PROVISIONS\n"
        "(Base your analysis ONLY on these provisions. "
        "Cite their article numbers. Do not use law outside this list.)\n\n"
        + _format_passages(passages)
    )

    return (
        "REGULATORY COMPLIANCE ASSESSMENT REQUEST\n\n"
        f"{case_block}\n\n"
        f"{provisions_block}\n\n"
        "Deliver your compliance assessment in the required JSON format. "
        "Cite only articles you actually used from the list above."
    )


# ── Public interface ───────────────────────────────────────────────────────────

def assess_compliance(client_record: dict) -> dict:
    """
    Run the Dynamic Compliance agent against one client record.

    Retrieves relevant regulatory provisions, injects them into the model prompt,
    and uses DynamicComplianceVerdict schema with json_schema strict mode
    (google/gemini-2.5-pro primary, gpt-4o fallback — both on AI/ML API).

    Returns:
        {
            "agent":        "dynamic_compliance",
            "verdict":      "pass" | "fail",
            "summary":      str,
            "jurisdiction": str,
            "citations":    list[str],
            "concerns":     list[str],
            "retrieved_k":  int,
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        On ModelUnavailableError: fail verdict — a model outage must never
        silently clear compliance.
    """
    request_id      = client_record.get("request_id", "UNKNOWN")
    nationality     = client_record.get("nationality", "")
    asset_type      = client_record.get("asset_type", "")
    asset_value     = client_record.get("asset_value_eur", 0)
    source_of_funds = client_record.get("source_of_funds", "")
    jurisdiction    = _map_jurisdiction(nationality)

    logger.info(
        "dynamic_compliance: starting assessment for %s jurisdiction=%s",
        request_id, jurisdiction,
    )

    # ── Step 1: Retrieve relevant law ─────────────────────────────────────────
    retrieval_query = _build_retrieval_query(
        asset_type, asset_value, source_of_funds, jurisdiction
    )
    passages = retrieve_relevant_law(
        query=retrieval_query,
        asset_type=asset_type,
        jurisdiction=jurisdiction,
        k=_RETRIEVAL_K,
    )
    logger.info(
        "dynamic_compliance: %s retrieved %d passages (top score %.4f)",
        request_id, len(passages), passages[0]["score"] if passages else 0,
    )

    # ── Step 2: Call model with schema enforcement ─────────────────────────────
    prompt = _build_prompt(client_record, passages, jurisdiction)

    try:
        response = call_agent_model(
            "dynamic_compliance", prompt, _SYSTEM_PROMPT,
            schema=DynamicComplianceVerdict,
        )
    except ModelUnavailableError as exc:
        logger.error(
            "dynamic_compliance: all models unavailable for %s — %s", request_id, exc
        )
        return {
            "agent": "dynamic_compliance",
            "verdict": "fail",
            "summary": (
                "All models unavailable — compliance clearance cannot be issued. "
                f"Escalating to human reviewer. Detail: {exc}"
            ),
            "jurisdiction": jurisdiction,
            "citations": [],
            "concerns": ["model_unavailable"],
            "retrieved_k": len(passages),
            "model_used": "none",
            "was_fallback": False,
            "latency_ms": 0,
        }

    data: DynamicComplianceVerdict = response.data

    logger.info(
        "dynamic_compliance: %s → verdict=%s citations=%d model=%s fallback=%s latency_ms=%d",
        request_id, data.verdict, len(data.citations),
        response.model_used, response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "dynamic_compliance",
        "verdict": data.verdict,
        "summary": data.summary,
        "jurisdiction": data.jurisdiction,
        "citations": data.citations,
        "concerns": data.concerns,
        "retrieved_k": len(passages),
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
