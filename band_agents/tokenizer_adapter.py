"""
band_agents/tokenizer_adapter.py
Brightuity — Band adapter for Asset Tokenizer agent (Phase 2e).

Mirrors stresstest_adapter.py exactly in structure. Connects the existing
design_token_structure() engine to the Band platform over WebSocket.

When a user @-mentions the agent with a request_id (e.g. "REQ-2041"):
  1. Parses request_id (same regex as all other adapters).
  2. Looks up the client record (same loader).
  3. Calls design_token_structure() — the UNCHANGED engine function.
  4. Posts a human-readable proposal via send_message(..., mentions=[sender])
     showing the token standard, supply, per-token value, and structure notes.
  5. Posts structured metadata via send_event() for downstream tooling.

Note: this agent assumes all prior gates have passed (as the engine does).
It proposes a structure for review — it does NOT mint tokens or make a
final issuance decision.

PII guard: passport_number, DOB, address, full_name are never posted.
Asset type, value, and token structure details reach the room; that is the
same boundary as the stresstest adapter.

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

from agents.asset_tokenizer.logic import design_token_structure

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
    Format the token structure proposal as a human-readable Band message.

    Shows verdict, token standard, supply, per-token value, summary, and
    structure notes. No PII beyond asset details already in the engine output.
    """
    verdict     = result.get("verdict", "unknown").upper()
    summary     = result.get("summary", "")
    standard    = result.get("token_standard", "unknown")
    total       = result.get("total_tokens", 0)
    per_token   = result.get("value_per_token_eur", 0.0)
    notes       = result.get("structure_notes") or []
    model       = result.get("model_used", "unknown")
    latency     = result.get("latency_ms", 0)
    was_fb      = result.get("was_fallback", False)

    icon = "PASS" if verdict == "PASS" else "FAIL"

    lines = [
        f"[{icon}] **Asset Tokenizer** — `{request_id}` — **{verdict}**",
        f"Standard: **{standard}** | Supply: **{total:,} tokens** @ "
        f"**EUR {per_token:,.2f}** per token",
        "",
        summary,
    ]

    if notes:
        lines += ["", "**Structure notes:**"]
        lines += [f"- {note}" for note in notes]

    fallback_note = " *(fallback model)*" if was_fb else ""
    lines += ["", f"*Model: {model}{fallback_note} · {latency} ms*"]

    return "\n".join(lines)


class AssetTokenizerAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band SimpleAdapter that routes @mention messages to the Asset Tokenizer engine.

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

        # Capture sender UUID for reply mentions — same pattern as all adapters.
        sender = msg.sender_id

        match = _REQ_ID_RE.search(content)
        if not match:
            await tools.send_message(
                "I need a **request_id** to design a token structure. "
                "Example: `@AssetTokenizer REQ-2041`",
                mentions=[sender],
            )
            return

        request_id = match.group(1).upper()
        scope_url = os.getenv("SCOPE_SERVICE_URL", "").strip()
        if scope_url:
            try:
                _pii_resp = httpx.get(
                    f"{scope_url}/scope/asset_tokenizer/{request_id}",
                    timeout=10.0,
                )
                if _pii_resp.status_code == 404:
                    await tools.send_message(
                        f"No client found for `{request_id}`. "
                        "Check the request_id and try again.",
                        mentions=[sender],
                    )
                    return
                _pii_resp.raise_for_status()
                client: dict[str, Any] = _pii_resp.json()
            except Exception as exc:
                logger.exception("PII gateway error for %s", request_id)
                await tools.send_message(
                    f"Token structure design failed for `{request_id}`: "
                    f"PII gateway unavailable — {exc}",
                    mentions=[sender],
                )
                return
        else:
            client = _CLIENT_INDEX.get(request_id)
            if client is None:
                await tools.send_message(
                    f"No client found for `{request_id}`. "
                    "Check the request_id and try again.",
                    mentions=[sender],
                )
                return

        key = (room_id, request_id)
        if key in self._in_flight:
            logger.debug("Tokenizer: duplicate @mention for %s in room %s — ignoring", request_id, room_id)
            return
        self._in_flight.add(key)
        try:
            await tools.send_message(
                f"Designing token structure for `{request_id}`… "
                "(GPT-4o structuring — may take a few seconds)",
                mentions=[sender],
            )

            try:
                result = await asyncio.to_thread(design_token_structure, client)
            except Exception as exc:
                logger.exception("design_token_structure failed for %s", request_id)
                await tools.send_message(
                    f"Token structure design failed for `{request_id}`: {exc}",
                    mentions=[sender],
                )
                return

            reply = _format_reply(request_id, result)
            await tools.send_message(reply, mentions=[sender])

            metadata: dict[str, Any] = {
                "agent":               "asset_tokenizer",
                "request_id":          request_id,
                "verdict":             result.get("verdict"),
                "token_standard":      result.get("token_standard"),
                "total_tokens":        result.get("total_tokens"),
                "value_per_token_eur": result.get("value_per_token_eur"),
                "model_used":          result.get("model_used"),
                "was_fallback":        result.get("was_fallback"),
                "latency_ms":          result.get("latency_ms"),
            }
            await tools.send_event(
                content=f"token_structure_result:{request_id}",
                message_type="tool_result",
                metadata=metadata,
            )
            logger.info(
                "Token structure posted to Band room %s — %s → %s (%s, %d tokens @ EUR %.2f)",
                room_id, request_id, result.get("verdict"),
                result.get("token_standard"), result.get("total_tokens", 0),
                result.get("value_per_token_eur", 0.0),
            )
        finally:
            self._in_flight.discard(key)
