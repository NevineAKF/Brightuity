"""
band_agents/kyc_adapter.py
Brightuity — Band adapter for KYC Guardian agent (Phase 2a spike).

Connects the existing screen_kyc() engine to the Band platform over WebSocket.
When a user @-mentions the agent with a request_id (e.g. "REQ-2041"), the adapter:
  1. Looks up the client record from the local JSON dataset (Zone 1 proxy).
  2. Calls screen_kyc() — the UNCHANGED engine function.
  3. Posts a human-readable verdict via send_message().
  4. Posts structured screening metadata via send_event() for downstream tooling.

PII guard: only verdict, match_type, match_score, watchlist_id, model_used, and
latency_ms are emitted to the Band room. passport_number, DOB, address, and
full_name are never posted beyond what the verdict summary already contains.

Immutability contract: this file NEVER imports from agents/ or shared/ for
anything other than the public screen_kyc() call. The engine is read-only here.
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

from agents.kyc_guardian.logic import screen_kyc

logger = logging.getLogger(__name__)

# Path to the JSON client dataset (Zone 1 proxy — read-only).
_CLIENTS_JSON = Path(__file__).parent.parent / "database" / "brightuity_clients.json"

# Pattern: capture a request_id token anywhere in the message.
# Matches REQ-<digits> (case-insensitive).
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
    Format the KYC screening result as a human-readable Band message.

    Only includes fields safe for the room; no PII beyond the verdict summary.
    """
    verdict   = result.get("verdict", "unknown").upper()
    summary   = result.get("summary", "")
    flags     = result.get("flags_raised") or []
    screening = result.get("screening_result") or {}
    model     = result.get("model_used", "unknown")
    latency   = result.get("latency_ms", 0)
    was_fb    = result.get("was_fallback", False)

    emoji_map = {"PASS": "✅", "FAIL": "❌", "HALT": "🚨"}
    icon = emoji_map.get(verdict, "❓")

    lines = [
        f"{icon} **KYC Guardian** — `{request_id}` — **{verdict}**",
        "",
        summary,
    ]

    if flags:
        lines += ["", "**Flags raised:**"]
        lines += [f"- {f}" for f in flags]

    matched = screening.get("matched", False)
    if matched:
        lines += [
            "",
            f"**Watchlist hit:** `{screening.get('watchlist_id') or screening.get('matched_entry', {}).get('id', 'unknown')}`",
            f"Match type: {screening.get('match_type', 'unknown')} "
            f"(score {screening.get('match_score', 0):.2f})",
            f"Sources checked: {', '.join(screening.get('sources_checked') or [])}",
        ]

    fallback_note = " *(fallback model)*" if was_fb else ""
    lines += ["", f"*Model: {model}{fallback_note} · {latency} ms*"]

    return "\n".join(lines)


class KycAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band SimpleAdapter that routes @mention messages to the KYC Guardian engine.

    History is unused (no LLM in the loop for this spike) — we type it as
    list and ignore it. The adapter is intentionally stateless: each message
    is self-contained.
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

        # Capture the sender's ID for use in all reply mentions.
        # PlatformMessage carries sender_id (UUID) but no handle field;
        # AgentTools._resolve_mentions() resolves UUIDs via its id_to_participant
        # lookup, so passing the raw UUID is the correct approach here.
        sender = msg.sender_id

        # Extract request_id from message (case-insensitive).
        match = _REQ_ID_RE.search(content)
        if not match:
            await tools.send_message(
                "I need a **request_id** to run KYC screening. "
                "Example: `@KycGuardian REQ-2041`",
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
            f"Running KYC screening for `{request_id}`… (this may take a few seconds)",
            mentions=[sender],
        )

        try:
            result = screen_kyc(client)
        except Exception as exc:
            logger.exception("screen_kyc failed for %s", request_id)
            await tools.send_message(
                f"KYC screening failed for `{request_id}`: {exc}",
                mentions=[sender],
            )
            return

        # Human-readable verdict.
        reply = _format_reply(request_id, result)
        await tools.send_message(reply, mentions=[sender])

        # Structured metadata for downstream tooling (no PII).
        screening = result.get("screening_result") or {}
        metadata: dict[str, Any] = {
            "agent":        "kyc_guardian",
            "request_id":   request_id,
            "verdict":      result.get("verdict"),
            "match_type":   screening.get("match_type"),
            "match_score":  screening.get("match_score"),
            "watchlist_id": (
                screening.get("watchlist_id")
                or (screening.get("matched_entry") or {}).get("id")
            ),
            "sources_checked": screening.get("sources_checked"),
            "model_used":   result.get("model_used"),
            "was_fallback": result.get("was_fallback"),
            "latency_ms":   result.get("latency_ms"),
        }
        await tools.send_event(
            content=f"kyc_screening_result:{request_id}",
            message_type="tool_result",
            metadata=metadata,
        )
        logger.info(
            "KYC screening posted to Band room %s — %s → %s",
            room_id, request_id, result.get("verdict"),
        )
