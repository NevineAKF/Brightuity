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
  5. Parse the JSON verdict including the citations array.

Public interface:
    assess_compliance(client_record: dict) -> dict
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from agents.dynamic_compliance.retrieval import retrieve_relevant_law
from shared.call_agent_model import ModelUnavailableError, call_agent_model

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT: str = (
    Path(__file__).parent / "system_prompt.txt"
).read_text(encoding="utf-8")

# Fields this agent reads from the client record.
# KYC fields (kyc_status, kyc_flags), document fields, risk_flags,
# and expected_outcome are deliberately excluded.
_COMPLIANCE_FIELDS: frozenset[str] = frozenset({
    "request_id",
    "full_name",
    "nationality",
    "asset_type",
    "asset_detail",
    "asset_value_eur",
    "source_of_funds",    # determines which AMLD obligations apply
    "source_verifiable",  # determines whether EDD source-of-funds requirement is met
})

# Countries whose nationals fall under EU regulatory jurisdiction (MiCA + AMLD).
# Extend this set when adding FCA (UK) or VARA (UAE) corpus entries.
_EU_MEMBER_STATES: frozenset[str] = frozenset({
    "Germany", "France", "Italy", "Spain", "Netherlands", "Belgium",
    "Austria", "Portugal", "Greece", "Cyprus", "Luxembourg", "Ireland",
    "Denmark", "Sweden", "Finland", "Poland", "Czech Republic", "Hungary",
    "Romania", "Bulgaria", "Croatia", "Slovakia", "Slovenia", "Estonia",
    "Latvia", "Lithuania", "Malta",
})

# Number of passages to retrieve per case. 6 gives 3–4 MiCA + 2–3 AMLD
# provisions in practice, enough for a grounded opinion without flooding context.
_RETRIEVAL_K = 6


# ── Jurisdiction mapping ───────────────────────────────────────────────────────

def _map_jurisdiction(nationality: str) -> str:
    """Map client nationality to the governing regulatory framework."""
    if nationality in _EU_MEMBER_STATES:
        return "EU"
    # Placeholder for future corpus expansions:
    # if nationality in _UK_RESIDENTS:  return "UK"
    # if nationality in _UAE_RESIDENTS: return "UAE"
    return "EU"  # Meridian Digital Bank is EU-incorporated; default to EU framework


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _build_retrieval_query(
    asset_type: str,
    asset_value_eur: int | float,
    source_of_funds: str,
    jurisdiction: str,
) -> str:
    """
    Construct the semantic retrieval query for this case.
    Encodes both the MiCA (token structure) and AMLD (bank obligations) questions
    so the vector search surfaces relevant provisions from both corpuses.
    """
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
    """Format retrieved passages as numbered law references for the prompt."""
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
    The model sees only compliance-relevant case facts and the retrieved law.
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
        f"REGULATORY COMPLIANCE ASSESSMENT REQUEST\n\n"
        f"{case_block}\n\n"
        f"{provisions_block}\n\n"
        "Deliver your compliance assessment in the required JSON format. "
        "Cite only articles you actually used from the list above."
    )


# ── Response parsing ───────────────────────────────────────────────────────────

def _parse_verdict(raw: str) -> tuple[str, str, str, list[str], list[str]]:
    """
    Parse the model's JSON into (verdict, summary, jurisdiction, citations, concerns).

    Handles <think> blocks, markdown fences, and surrounding prose.
    Uses raw_decode() so it stops at the end of the first valid JSON object
    rather than guessing brace positions — robust against trailing content.
    Falls back to ("fail", error_message, "EU", [], ["json_parse_error"]) on bad output.
    """
    text = raw.strip()

    # Strip reasoning-model think blocks (Gemini may include chain-of-thought)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Extract content between markdown code fences if present (Gemini wraps in ```json)
    fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        # No fences: remove any stray fence markers (```json or ```) and trim
        text = re.sub(r"```(?:json)?", "", text).strip()

    # Find the first { and attempt raw_decode from there — stops at end of first
    # valid JSON object, ignoring any trailing prose or content.
    brace_start = text.find("{")
    if brace_start < 0:
        logger.warning(
            "dynamic_compliance: no JSON object found. Raw (first 400 chars): %.400s", raw,
        )
        return (
            "fail",
            "Parse error: model response contained no JSON object. Manual review required.",
            "EU",
            [],
            ["json_parse_error"],
        )

    try:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(text, brace_start)

        verdict = str(data.get("verdict", "fail")).lower().strip()
        if verdict not in ("pass", "fail"):
            logger.warning(
                "dynamic_compliance: unexpected verdict %r — defaulting to fail", verdict
            )
            verdict = "fail"

        summary      = str(data.get("summary", "")).strip() or "No summary provided."
        jurisdiction  = str(data.get("jurisdiction", "EU")).strip() or "EU"
        citations     = [str(c) for c in data.get("citations", [])]
        concerns      = [str(c) for c in data.get("concerns", [])]

        return verdict, summary, jurisdiction, citations, concerns

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning(
            "dynamic_compliance: JSON parse failed (%s). Raw (first 400 chars): %.400s",
            exc, raw,
        )
        return (
            "fail",
            "Parse error: model response was not valid JSON. Manual review required.",
            "EU",
            [],
            ["json_parse_error"],
        )


# ── Public interface ───────────────────────────────────────────────────────────

def assess_compliance(client_record: dict) -> dict:
    """
    Run the Dynamic Compliance agent against one client record.

    Retrieves the most relevant regulatory provisions for this case from the
    ChromaDB knowledge base, injects them into the model prompt alongside the
    case facts, and instructs the model to ground its opinion exclusively in
    the retrieved passages. The returned 'citations' field lists the article
    numbers the model actually used — proving the opinion is not hallucinated.

    Args:
        client_record: One client dict from brightuity_clients.json (or DB1).
                       Only compliance-relevant fields (_COMPLIANCE_FIELDS) are
                       used in the prompt. expected_outcome is never accessed.

    Returns:
        {
            "agent":        "dynamic_compliance",
            "verdict":      "pass" | "fail",
            "summary":      str,
            "jurisdiction": str,       # e.g. "EU — MiCA + AMLD"
            "citations":    list[str], # articles actually used in the opinion
            "concerns":     list[str], # empty list when verdict is "pass"
            "retrieved_k":  int,       # number of passages retrieved (audit trail)
            "model_used":   str,
            "was_fallback": bool,
            "latency_ms":   int,
        }

        On ModelUnavailableError, returns a "fail" verdict so the Consensus
        Signer blocks — a model outage must never silently clear compliance.
    """
    request_id  = client_record.get("request_id", "UNKNOWN")
    nationality = client_record.get("nationality", "")
    asset_type  = client_record.get("asset_type", "")
    asset_value = client_record.get("asset_value_eur", 0)
    source_of_funds = client_record.get("source_of_funds", "")

    jurisdiction = _map_jurisdiction(nationality)

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

    # ── Step 2: Build prompt and call model ───────────────────────────────────
    prompt = _build_prompt(client_record, passages, jurisdiction)

    try:
        response = call_agent_model("dynamic_compliance", prompt, _SYSTEM_PROMPT)
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

    # ── Step 3: Parse and return ──────────────────────────────────────────────
    verdict, summary, jur_out, citations, concerns = _parse_verdict(response.text)

    logger.info(
        "dynamic_compliance: %s → verdict=%s citations=%d model=%s fallback=%s latency_ms=%d",
        request_id, verdict, len(citations),
        response.model_used, response.was_fallback, response.latency_ms,
    )

    return {
        "agent": "dynamic_compliance",
        "verdict": verdict,
        "summary": summary,
        "jurisdiction": jur_out,
        "citations": citations,
        "concerns": concerns,
        "retrieved_k": len(passages),
        "model_used": response.model_used,
        "was_fallback": response.was_fallback,
        "latency_ms": response.latency_ms,
    }
