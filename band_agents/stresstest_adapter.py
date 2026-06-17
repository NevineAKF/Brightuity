"""
band_agents/stresstest_adapter.py
Brightuity — Band adapter for Stress-Test Simulator agent (Phase 2d).

Mirrors docauditor_adapter.py exactly in structure. Connects the existing
run_stress_test() engine to the Band platform over WebSocket.

Architecture note: risk_score, risk_level (risk_band), and verdict are
DETERMINISTIC — computed by the parametric risk engine BEFORE the LLM runs.
The LLM (DeepSeek-V4-Pro primary, Qwen fallback) provides only the
interpretive narrative (summary + enriched risk_factors). The adapter reports
the engine numbers faithfully and never re-derives them.

When a user @-mentions the agent with a request_id (e.g. "REQ-2043"):
  1. Parses request_id (same regex as all other adapters).
  2. Looks up the client record (same loader).
  3. Calls run_stress_test() — the UNCHANGED engine function.
  4. Posts a human-readable verdict via send_message(..., mentions=_mention_targets)
     showing verdict, risk_score/risk_band, summary, and key risk_factors.
  5. Posts structured metadata via send_event() for downstream tooling.

PII guard: passport_number, DOB, address, full_name are never posted.
Only risk metrics and the LLM narrative reach the Band room.

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

from agents.stress_test.logic import run_stress_test

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
    Format the stress-test result as a human-readable Band message.

    Shows deterministic engine numbers (risk_score, risk_band) first — these
    are authoritative. LLM narrative (summary, risk_factors) follows.
    No PII beyond asset type/value already in the engine output.
    """
    verdict      = result.get("verdict", "unknown").upper()
    summary      = result.get("summary", "")
    risk_level   = result.get("risk_level", "unknown").upper()
    risk_factors = result.get("risk_factors") or []
    model        = result.get("model_used", "unknown")
    latency      = result.get("latency_ms", 0)
    was_fb       = result.get("was_fallback", False)

    rm          = result.get("risk_metrics") or {}
    risk_score  = rm.get("risk_score", "n/a")
    base_val    = rm.get("base_valuation", 0)
    sv          = rm.get("stressed_value_range") or {}
    worst_case  = sv.get("worst_case_eur")

    icon = "PASS" if verdict == "PASS" else "FAIL"

    lines = [
        f"[{icon}] **Stress-Test Simulator** — `{request_id}` — **{verdict}**",
        f"Risk score: **{risk_score}/100** | Risk band: **{risk_level}**",
        "",
        summary,
    ]

    if worst_case is not None and base_val:
        worst_pct = (worst_case - base_val) / base_val * 100
        lines += [
            "",
            f"**Stressed value (worst case):** EUR {worst_case:,.0f} "
            f"({worst_pct:+.1f}% vs base EUR {base_val:,.0f})",
        ]

    if risk_factors:
        lines += ["", "**Key risk factors:**"]
        lines += [f"- {f}" for f in risk_factors]

    fallback_note = " *(fallback model)*" if was_fb else ""
    lines += ["", f"*Model: {model}{fallback_note} · {latency} ms*"]

    return "\n".join(lines)


class StressTestAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band SimpleAdapter that routes @mention messages to the Stress-Test engine.

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
        _backend_id = os.getenv("BAND_BACKEND_AGENT_ID", "")
        _mention_targets = [m for m in [sender, _backend_id] if m]

        match = _REQ_ID_RE.search(content)
        if not match:
            await tools.send_message(
                "I need a **request_id** to run a stress-test. "
                "Example: `@StressTest REQ-2041`",
                mentions=_mention_targets,
            )
            return

        request_id = match.group(1).upper()
        scope_url = os.getenv("SCOPE_SERVICE_URL", "").strip()
        if scope_url:
            try:
                _pii_resp = httpx.get(
                    f"{scope_url}/scope/stress_test/{request_id}",
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
                    f"Stress-test failed for `{request_id}`: "
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
            logger.debug("StressTest: duplicate @mention for %s in room %s — ignoring", request_id, room_id)
            return
        self._in_flight.add(key)
        try:
            await tools.send_message(
                f"Running stress-test for `{request_id}`… "
                "(deterministic risk engine + DeepSeek narrative)",
                mentions=_mention_targets,
            )

            try:
                result = await asyncio.to_thread(run_stress_test, client)
            except Exception as exc:
                logger.exception("run_stress_test failed for %s", request_id)
                await tools.send_message(
                    f"Stress-test failed for `{request_id}`: {exc}",
                    mentions=_mention_targets,
                )
                return

            reply = _format_reply(request_id, result)
            await tools.send_message(reply, mentions=_mention_targets)

            rm = result.get("risk_metrics") or {}
            metadata: dict[str, Any] = {
                "agent":        "stress_test",
                "request_id":   request_id,
                "verdict":      result.get("verdict"),
                "risk_score":   rm.get("risk_score"),
                "risk_band":    result.get("risk_level"),   # engine field name is risk_level
                "model_used":   result.get("model_used"),
                "was_fallback": result.get("was_fallback"),
                "latency_ms":   result.get("latency_ms"),
            }
            await tools.send_event(
                content=f"stress_test_result:{request_id}",
                message_type="tool_result",
                metadata=metadata,
            )
            logger.info(
                "Stress-test posted to Band room %s — %s → %s (risk_score=%s risk_band=%s)",
                room_id, request_id, result.get("verdict"),
                rm.get("risk_score"), result.get("risk_level"),
            )
        finally:
            self._in_flight.discard(key)
