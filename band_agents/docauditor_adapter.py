"""
band_agents/docauditor_adapter.py
Brightuity — Band adapter for Doc Auditor agent (Phase 2c).

Mirrors compliance_adapter.py exactly in structure. Connects the existing
audit_documents() engine to the Band platform over WebSocket.

When a user @-mentions the agent with a request_id (e.g. "REQ-2041"):
  1. Parses request_id from the message (same regex as KYC / Compliance).
  2. Looks up the client record from the local JSON dataset (same loader).
  3. Calls audit_documents() — the UNCHANGED engine function.
  4. Posts a human-readable verdict via send_message(..., mentions=_mention_targets).
  5. Posts structured metadata via send_event() for downstream tooling.

PII guard: passport_number, DOB, address are never posted. The verdict
summary may reference the applicant's name (as the engine returned it) and
asset details — the same boundary compliance_adapter uses.

Engine is read-only: this file NEVER modifies agents/ or shared/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from band.core.simple_adapter import SimpleAdapter
from band.core.protocols import AgentToolsProtocol
from band.core.types import PlatformMessage

from agents.doc_auditor.logic import audit_documents

logger = logging.getLogger(__name__)

_CLIENTS_JSON = Path(__file__).parent.parent / "database" / "brightuity_clients.json"

_REQ_ID_RE = re.compile(r"\b(REQ-\d+)\b", re.IGNORECASE)


def _load_client_index() -> dict[str, dict[str, Any]]:
    with open(_CLIENTS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["request_id"]: c for c in data["clients"]}


_CLIENT_INDEX: dict[str, dict[str, Any]] = _load_client_index()


def _format_reply(request_id: str, result: dict[str, Any]) -> str:
    """
    Format the document audit result as a human-readable Band message.

    Shows verdict, summary, and any document issues found.
    No PII beyond what the engine's summary already contains.
    """
    verdict  = result.get("verdict", "unknown").upper()
    summary  = result.get("summary", "")
    issues   = result.get("issues_found") or []
    model    = result.get("model_used", "unknown")
    latency  = result.get("latency_ms", 0)
    was_fb   = result.get("was_fallback", False)

    icon = "PASS" if verdict == "PASS" else "FAIL"

    lines = [
        f"[{icon}] **Doc Auditor** — `{request_id}` — **{verdict}**",
        "",
        summary,
    ]

    if issues:
        lines += ["", "**Document issues found:**"]
        lines += [f"- {issue}" for issue in issues]

    fallback_note = " *(fallback model)*" if was_fb else ""
    lines += ["", f"*Model: {model}{fallback_note} · {latency} ms*"]

    return "\n".join(lines)


class DocAuditorAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band SimpleAdapter that routes @mention messages to the Doc Auditor engine.

    History is unused — typed as list and ignored. Stateless: each message
    is self-contained.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_flight: set[tuple[str, str]] = set()

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

        # Capture sender UUID for reply mentions — same pattern as kyc_adapter
        # and compliance_adapter. AgentTools._resolve_mentions() resolves the
        # UUID via id_to_participant lookup.
        sender = msg.sender_id
        _backend_id = os.getenv("BAND_BACKEND_AGENT_ID", "")
        _mention_targets = [m for m in [sender, _backend_id] if m]

        match = _REQ_ID_RE.search(content)
        if not match:
            await tools.send_message(
                "I need a **request_id** to run a document audit. "
                "Example: `@DocAuditor REQ-2041`",
                mentions=_mention_targets,
            )
            return

        request_id = match.group(1).upper()
        scope_url = os.getenv("SCOPE_SERVICE_URL", "").strip()
        if scope_url:
            try:
                _pii_resp = httpx.get(
                    f"{scope_url}/scope/doc_auditor/{request_id}",
                    timeout=10.0,
                )
                if _pii_resp.status_code == 404:
                    await tools.send_message(
                        f"No client found for `{request_id}`. "
                        "Check the request_id and try again.",
                        mentions=_mention_targets,
                    )
                    return
                _pii_resp.raise_for_status()
                client: dict[str, Any] = _pii_resp.json()
            except Exception as exc:
                logger.exception("PII gateway error for %s", request_id)
                await tools.send_message(
                    f"Document audit failed for `{request_id}`: "
                    f"PII gateway unavailable — {exc}",
                    mentions=_mention_targets,
                )
                return
        else:
            client = _CLIENT_INDEX.get(request_id)
            if client is None:
                await tools.send_message(
                    f"No client found for `{request_id}`. "
                    "Check the request_id and try again.",
                    mentions=_mention_targets,
                )
                return

        key = (room_id, request_id)
        if key in self._in_flight:
            logger.debug("DocAuditor: duplicate @mention for %s in room %s — ignoring", request_id, room_id)
            return
        self._in_flight.add(key)
        try:
            await tools.send_message(
                f"Running document audit for `{request_id}`… "
                "(this may take a few seconds)",
                mentions=_mention_targets,
            )

            try:
                result = await asyncio.to_thread(audit_documents, client)
            except Exception as exc:
                logger.exception("audit_documents failed for %s", request_id)
                await tools.send_message(
                    f"Document audit failed for `{request_id}`: {exc}",
                    mentions=_mention_targets,
                )
                return

            reply = _format_reply(request_id, result)
            await tools.send_message(reply, mentions=_mention_targets)

            metadata: dict[str, Any] = {
                "agent":        "doc_auditor",
                "request_id":   request_id,
                "verdict":      result.get("verdict"),
                "issues_found": result.get("issues_found"),
                "model_used":   result.get("model_used"),
                "was_fallback": result.get("was_fallback"),
                "latency_ms":   result.get("latency_ms"),
            }
            await tools.send_event(
                content=f"doc_audit_result:{request_id}",
                message_type="tool_result",
                metadata=metadata,
            )
            logger.info(
                "Doc audit posted to Band room %s — %s → %s",
                room_id, request_id, result.get("verdict"),
            )
        finally:
            self._in_flight.discard(key)
