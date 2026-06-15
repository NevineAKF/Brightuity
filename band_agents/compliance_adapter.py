"""
band_agents/compliance_adapter.py
Brightuity — Band adapter for Dynamic Compliance agent (Phase 2b).

Mirrors kyc_adapter.py exactly in structure. Connects the existing
assess_compliance() engine to the Band platform over WebSocket.

When a user @-mentions the agent with a request_id (e.g. "REQ-2041"):
  1. Parses request_id from the message (same regex as KYC adapter).
  2. Looks up the client record from the local JSON dataset (same loader).
  3. Calls assess_compliance() — the UNCHANGED engine function.
  4. Posts a human-readable verdict via send_message(..., mentions=[sender]).
  5. Posts structured metadata via send_event() for downstream tooling.

PII guard: passport_number, DOB, address, and full_name are never posted.
Only verdict, jurisdiction, citations (article numbers), concerns, model info,
and latency are emitted. The summary may contain the applicant's name exactly
as the engine returned it — that is the same boundary the KYC adapter uses.

Engine is read-only: this file NEVER modifies agents/ or shared/.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from band.core.simple_adapter import SimpleAdapter
from band.core.protocols import AgentToolsProtocol
from band.core.types import PlatformMessage

from agents.dynamic_compliance.logic import assess_compliance

logger = logging.getLogger(__name__)

# Path to the JSON client dataset (Zone 1 proxy — read-only).
_CLIENTS_JSON = Path(__file__).parent.parent / "database" / "brightuity_clients.json"

# Same regex as kyc_adapter — matches REQ-<digits> anywhere in the message.
_REQ_ID_RE = re.compile(r"\b(REQ-\d+)\b", re.IGNORECASE)


def _load_client_index() -> dict[str, dict[str, Any]]:
    """Return {request_id: client_record} from the JSON dataset."""
    with open(_CLIENTS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["request_id"]: c for c in data["clients"]}


# Load once at import time — the JSON file is static during the spike.
_CLIENT_INDEX: dict[str, dict[str, Any]] = _load_client_index()


def _format_reply(request_id: str, result: dict[str, Any]) -> str:
    """
    Format the compliance assessment result as a human-readable Band message.

    Shows verdict, jurisdiction, RAG citations, and any concerns.
    No PII beyond what the engine's summary already contains.
    """
    verdict      = result.get("verdict", "unknown").upper()
    summary      = result.get("summary", "")
    jurisdiction = result.get("jurisdiction", "unknown")
    citations    = result.get("citations") or []
    concerns     = result.get("concerns") or []
    model        = result.get("model_used", "unknown")
    latency      = result.get("latency_ms", 0)
    was_fb       = result.get("was_fallback", False)
    retrieved_k  = result.get("retrieved_k", 0)

    icon = "PASS" if verdict == "PASS" else "FAIL"

    lines = [
        f"[{icon}] **Dynamic Compliance** — `{request_id}` — **{verdict}** ({jurisdiction})",
        "",
        summary,
    ]

    if citations:
        lines += ["", "**RAG citations (grounding provisions):**"]
        lines += [f"- {c}" for c in citations]

    if concerns:
        lines += ["", "**Concerns raised:**"]
        lines += [f"- {c}" for c in concerns]

    fallback_note = " *(fallback model)*" if was_fb else ""
    lines += [
        "",
        f"*Model: {model}{fallback_note} · {latency} ms · {retrieved_k} provisions retrieved*",
    ]

    return "\n".join(lines)


class ComplianceAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band SimpleAdapter that routes @mention messages to the Dynamic Compliance engine.

    History is unused (no LLM orchestration in the adapter layer) — typed as list
    and ignored. The adapter is intentionally stateless: each message is self-contained.
    """

    async def on_message(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        history: list,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        content = (msg.content or "").strip()

        # Capture the sender's ID for reply mentions.
        # PlatformMessage carries sender_id (UUID); AgentTools._resolve_mentions()
        # resolves it via id_to_participant lookup — same pattern as kyc_adapter.
        sender = msg.sender_id

        # Extract request_id (case-insensitive).
        match = _REQ_ID_RE.search(content)
        if not match:
            await tools.send_message(
                "I need a **request_id** to run a compliance assessment. "
                "Example: `@DynamicCompliance REQ-2041`",
                mentions=[sender],
            )
            return

        request_id = match.group(1).upper()
        client = _CLIENT_INDEX.get(request_id)
        if client is None:
            await tools.send_message(
                f"No client found for `{request_id}`. "
                "Check the request_id and try again.",
                mentions=[sender],
            )
            return

        await tools.send_message(
            f"Running compliance assessment for `{request_id}`… "
            "(RAG retrieval + Gemini 2.5 Pro — may take a few seconds)",
            mentions=[sender],
        )

        try:
            result = assess_compliance(client)
        except Exception as exc:
            logger.exception("assess_compliance failed for %s", request_id)
            await tools.send_message(
                f"Compliance assessment failed for `{request_id}`: {exc}",
                mentions=[sender],
            )
            return

        # Human-readable verdict.
        reply = _format_reply(request_id, result)
        await tools.send_message(reply, mentions=[sender])

        # Structured metadata for downstream tooling (no PII).
        metadata: dict[str, Any] = {
            "agent":        "dynamic_compliance",
            "request_id":   request_id,
            "verdict":      result.get("verdict"),
            "jurisdiction": result.get("jurisdiction"),
            "citations":    result.get("citations"),
            "concerns":     result.get("concerns"),
            "retrieved_k":  result.get("retrieved_k"),
            "model_used":   result.get("model_used"),
            "was_fallback": result.get("was_fallback"),
            "latency_ms":   result.get("latency_ms"),
        }
        await tools.send_event(
            content=f"compliance_assessment_result:{request_id}",
            message_type="tool_result",
            metadata=metadata,
        )
        logger.info(
            "Compliance assessment posted to Band room %s — %s → %s",
            room_id, request_id, result.get("verdict"),
        )
