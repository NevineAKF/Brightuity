"""
band_agents/orchestrator_adapter.py  (Phase 2k — robust verdict collection)
Brightuity — Orchestrator Band adapter.

COORDINATION PATTERN (real Band, no in-process calls):
  1. Human @mentions "@Orchestrator REQ-xxxx"
     → Orchestrator posts FOUR separate messages — one per stage-1 agent, each
       @mentioning exactly one agent by UUID. Individual mentions are far more
       reliable than a 4-way fan-out.
     → A background chase task (_chase_verdicts) re-mentions any agent that has
       not replied within RETRY_INTERVAL seconds, up to MAX_RETRIES times.
     → If verdicts are still missing after all retries, the pipeline times out
       and escalates for manual review — it NEVER hangs indefinitely.
  2. Each specialist's send_message reply arrives in on_message as a MessageEvent
     (msg.sender_type="Agent", msg.sender_id=<specialist UUID>).
     → Orchestrator parses the verdict from msg.content (always contains **PASS**,
       **FAIL**, or **HALT** in bold) and stores it in per-room+request state.
  3. When all 4 stage-1 verdicts are collected → evaluate_governance_gate (core.py):
     - halt/blocked → post stop message + send_event, case complete.
     - pass → @mention Asset Tokenizer with the same REQ-id.
  4. Tokenizer reply arrives → Orchestrator runs ConsensusSigner.seal() in-process
     on the structured verdicts already held in case state (no chat-text re-parsing),
     then posts the ECDSA seal result labeled as the Consensus Signer step.

RETRY CONSTANTS:
  RETRY_INTERVAL = 25 s   — sleep between re-mention checks
  MAX_RETRIES    = 3      — re-mention attempts (~25 s, ~50 s, ~75 s before timeout)

STATE: self._cases[(room_id, request_id)] — persists across on_message() calls.
       asyncio is single-threaded; dict reads/writes are atomic between awaits.
       "chase_task" field: asyncio.Task handle; cancelled when all verdicts arrive.

GATE LOGIC: evaluate_governance_gate() from agents/orchestrator/core.py.
            KYC "halt" = absolute veto. Doc/KYC(non-halt)/Compliance non-pass =
            blocked. Stress-test is advisory at orchestrator level.

SENDER FIELDS used:
  msg.sender_type   — "User" (human trigger) | "Agent" (specialist verdict)
  msg.sender_id     — UUID; primary key for agent identity via _agent_id_map
  msg.sender_name   — display name; fallback for identity via _AGENT_NAME_MAP

VERDICT PARSING:
  All specialist adapters embed the verdict as **PASS**, **FAIL**, or **HALT**
  (bold markdown) in the first line of their send_message reply.
  _VERDICT_RE extracts it and returns lowercase to match gate expectations.

SEND_EVENT METADATA: send_event() metadata from specialists is NOT parsed here
  because it does not arrive in msg.metadata (MessageMetadata carries only
  mentions+status; the custom dict is stored platform-side). msg.content +
  msg.sender_type/sender_id is the reliable channel.

PII guard: never posts passport_number, DOB, address, full_name.
Engine is read-only: NEVER modifies agents/ or shared/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from band.core.simple_adapter import SimpleAdapter
from band.core.protocols import AgentToolsProtocol
from band.core.types import PlatformMessage

from agents.orchestrator.core import evaluate_governance_gate, seal_decision, build_decision_record

logger = logging.getLogger(__name__)

_CLIENTS_JSON     = Path(__file__).parent.parent / "database" / "brightuity_clients.json"
_BAND_RESULTS_DIR = Path(__file__).parent.parent / "database" / "band_results"

# ── Retry constants ─────────────────────────────────────────────────────────────
RETRY_INTERVAL: int = 25   # seconds between re-mention checks
MAX_RETRIES:    int = 3    # re-mention attempts before hard timeout (~75 s total)


def _load_client_index() -> dict[str, dict[str, Any]]:
    with open(_CLIENTS_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["request_id"]: c for c in data["clients"]}


_CLIENT_INDEX: dict[str, dict[str, Any]] = _load_client_index()

_REQ_ID_RE = re.compile(r"\b(REQ-\d+)\b", re.IGNORECASE)

# Extracts PASS / FAIL / HALT from bold markdown in specialist replies.
# All adapters use **{verdict.upper()}** — "PASS", "FAIL", or "HALT".
_VERDICT_RE = re.compile(r"\*\*(PASS|FAIL|HALT)\*\*", re.IGNORECASE)

# Stage-1 gate keys — must all report before gate is evaluated.
_STAGE1_GATES: tuple[str, ...] = (
    "doc_auditor",
    "kyc_guardian",
    "dynamic_compliance",
    "stress_test",
)

# Human-readable display names used in individual @mention messages.
_GATE_DISPLAY: dict[str, str] = {
    "doc_auditor":        "Doc Auditor",
    "kyc_guardian":       "KYC Guardian",
    "dynamic_compliance": "Dynamic Compliance",
    "stress_test":        "Stress-Test Simulator",
}

# Display-name fallback: Band sender_name → internal gate key.
# Used when sender_id isn't in _agent_id_map (e.g. env mismatch).
_AGENT_NAME_MAP: dict[str, str] = {
    "KYC Guardian":           "kyc_guardian",
    "Dynamic Compliance":     "dynamic_compliance",
    "Doc Auditor":            "doc_auditor",
    "Stress-Test Simulator":  "stress_test",
    "Asset Tokenizer":        "asset_tokenizer",
}


def _parse_verdict(content: str) -> str | None:
    """
    Extract verdict from a specialist's reply text.

    Returns lowercase "pass" / "fail" / "halt" (matching gate expectations),
    or None if no bold verdict token found.
    """
    m = _VERDICT_RE.search(content)
    return m.group(1).lower() if m else None


class OrchestratorAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band coordination adapter for the Orchestrator agent.

    Stateful across on_message() calls: self._cases holds per-room+request
    pipeline state so that specialist verdicts arriving in separate messages
    can be accumulated until the gate can be evaluated.

    A background _chase_verdicts task is started for each case to re-mention
    any agent that has not replied, ensuring the pipeline always terminates.
    """

    def __init__(self) -> None:
        super().__init__()

        # UUID → internal agent name; built from env at init (dotenv already loaded).
        raw: dict[str, str] = {
            os.environ.get("BAND_KYC_AGENT_ID", ""):        "kyc_guardian",
            os.environ.get("BAND_COMPLIANCE_AGENT_ID", ""): "dynamic_compliance",
            os.environ.get("BAND_DOCAUDITOR_AGENT_ID", ""): "doc_auditor",
            os.environ.get("BAND_STRESSTEST_AGENT_ID", ""): "stress_test",
            os.environ.get("BAND_TOKENIZER_AGENT_ID", ""):  "asset_tokenizer",
        }
        self._agent_id_map: dict[str, str] = {k: v for k, v in raw.items() if k}

        # Agent UUIDs used in mentions=[...] lists.
        self._kyc_id       = os.environ.get("BAND_KYC_AGENT_ID", "")
        self._comp_id      = os.environ.get("BAND_COMPLIANCE_AGENT_ID", "")
        self._doc_id       = os.environ.get("BAND_DOCAUDITOR_AGENT_ID", "")
        self._stress_id    = os.environ.get("BAND_STRESSTEST_AGENT_ID", "")
        self._token_id     = os.environ.get("BAND_TOKENIZER_AGENT_ID", "")
        self._consensus_id = os.environ.get("BAND_CONSENSUS_AGENT_ID", "")

        # gate key → UUID — used by chase task to send targeted re-mentions.
        self._gate_id_map: dict[str, str] = {
            "doc_auditor":        self._doc_id,
            "kyc_guardian":       self._kyc_id,
            "dynamic_compliance": self._comp_id,
            "stress_test":        self._stress_id,
        }

        # Per-(room_id, request_id) pipeline state.
        # {
        #   "initiator":   str,                   # human sender_id (all reply mentions)
        #   "state":       str,                   # awaiting_stage1 | awaiting_tokenizer
        #                                         # | complete | timeout
        #   "verdicts":    {gate_key: str|None},  # None until received
        #   "summaries":   {gate_key: str},       # first 300 chars of each reply (for seal)
        #   "chase_task":  asyncio.Task|None,     # background retry task — cancelled on
        #                                         # completion or when all verdicts arrive
        # }
        self._cases: dict[tuple[str, str], dict[str, Any]] = {}

    # ── Main entry point ───────────────────────────────────────────────────────

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
        sender  = msg.sender_id

        # ── Agent reply → accumulate verdict ──────────────────────────────────
        if msg.sender_type == "Agent":
            await self._collect_verdict(msg, tools, room_id, content, sender)
            return

        # ── Human trigger → start new pipeline case ───────────────────────────
        if msg.sender_type != "User":
            return  # skip system / unknown sender types

        req = _REQ_ID_RE.search(content)
        if not req:
            await tools.send_message(
                "I need a **request_id** to run the compliance pipeline. "
                "Example: `@Orchestrator REQ-2041`",
                mentions=[sender],
            )
            return

        request_id = req.group(1).upper()
        case_key   = (room_id, request_id)

        if case_key in self._cases:
            state = self._cases[case_key]["state"]
            await tools.send_message(
                f"`{request_id}` is already in progress (state: **{state}**). "
                "Waiting for remaining agent replies.",
                mentions=[sender],
            )
            return

        # Initialise case state.
        self._cases[case_key] = {
            "initiator":       sender,
            "state":           "awaiting_stage1",
            "verdicts":        {k: None for k in _STAGE1_GATES},
            "summaries":       {},
            "chase_task":      None,
            "gate_outcome":    None,
            "gate_reason":     None,
            "pipeline_status": None,
            "seal_result":     None,
        }
        logger.info("orchestrator: NEW CASE %s room=%s", request_id, room_id)

        # Post FOUR separate messages — one @mention per stage-1 agent.
        # Individual targeted mentions are far more reliably delivered than a
        # single combined fan-out message.
        stage1_pairs: list[tuple[str, str]] = [
            (self._doc_id,    "doc_auditor"),
            (self._kyc_id,    "kyc_guardian"),
            (self._comp_id,   "dynamic_compliance"),
            (self._stress_id, "stress_test"),
        ]
        for agent_id, gate in stage1_pairs:
            if agent_id:
                await tools.send_message(
                    f"@{_GATE_DISPLAY[gate]} — please report your verdict for `{request_id}`.",
                    mentions=[agent_id],
                )
                await asyncio.sleep(0.3)

        logger.info("orchestrator: %s sent initial mentions to 4 stage-1 agents", request_id)

        # Start the background retry / timeout task.
        # Stored on the case so _collect_verdict can cancel it when all verdicts arrive.
        chase = asyncio.create_task(
            self._chase_verdicts(tools, room_id, request_id)
        )
        self._cases[case_key]["chase_task"] = chase

    # ── Background chase / retry task ──────────────────────────────────────────

    async def _chase_verdicts(
        self,
        tools: AgentToolsProtocol,
        room_id: str,
        request_id: str,
    ) -> None:
        """
        Background task: actively pursue any stage-1 agent that has not replied.

        Sleeps RETRY_INTERVAL seconds, then re-mentions every agent whose verdict
        is still missing. Repeats up to MAX_RETRIES times (~25 s, ~50 s, ~75 s).
        After all retries, calls _handle_timeout() if verdicts are still absent.

        The task is cancelled (via Task.cancel()) by _collect_verdict as soon as
        all 4 verdicts arrive — no orphaned tasks.

        asyncio.CancelledError during sleep is caught and causes a clean return.
        """
        case_key = (room_id, request_id)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await asyncio.sleep(RETRY_INTERVAL)
            except asyncio.CancelledError:
                logger.info(
                    "orchestrator: chase task for %s cancelled — all verdicts arrived",
                    request_id,
                )
                return

            # Re-read live case state each iteration.
            case = self._cases.get(case_key)
            if case is None or case["state"] != "awaiting_stage1":
                logger.debug(
                    "orchestrator: chase for %s exiting — state is no longer awaiting_stage1",
                    request_id,
                )
                return

            missing = [g for g in _STAGE1_GATES if case["verdicts"].get(g) is None]
            if not missing:
                logger.info("orchestrator: %s all verdicts collected — chase task done", request_id)
                return

            logger.info(
                "orchestrator: %s still missing: %s (attempt %d/%d) — re-mentioning",
                request_id, missing, attempt, MAX_RETRIES,
            )
            for gate in missing:
                agent_id = self._gate_id_map.get(gate, "")
                if agent_id:
                    await tools.send_message(
                        f"@{_GATE_DISPLAY[gate]} — reminder: please report your verdict for `{request_id}`.",
                        mentions=[agent_id],
                    )
                    logger.info(
                        "orchestrator: re-mentioning %s attempt %d/%d",
                        gate, attempt, MAX_RETRIES,
                    )
                    try:
                        await asyncio.sleep(0.3)
                    except asyncio.CancelledError:
                        logger.info(
                            "orchestrator: chase for %s cancelled mid-retry", request_id,
                        )
                        return

        # All MAX_RETRIES re-mention loops completed — final check.
        case = self._cases.get(case_key)
        if case is None or case["state"] != "awaiting_stage1":
            return

        missing = [g for g in _STAGE1_GATES if case["verdicts"].get(g) is None]
        if missing:
            await self._handle_timeout(tools, case, case_key, request_id, missing)

    # ── Timeout fallback ───────────────────────────────────────────────────────

    async def _handle_timeout(
        self,
        tools: AgentToolsProtocol,
        case: dict,
        case_key: tuple[str, str],
        request_id: str,
        missing: list[str],
    ) -> None:
        """
        Safe terminal state when verdicts are still absent after all retries.

        Posts an escalation message, emits timeout_incomplete event.
        Does NOT proceed to tokenizer. Does NOT seal.
        """
        case["state"]           = "timeout"
        case["pipeline_status"] = "error"
        case["seal_result"]     = {
            "status": "blocked",
            "reason": "Pipeline timeout — verdicts not received within retry window.",
        }
        initiator       = case["initiator"]
        arrived         = {
            g: case["verdicts"][g]
            for g in _STAGE1_GATES
            if case["verdicts"].get(g) is not None
        }
        missing_display = ", ".join(_GATE_DISPLAY.get(g, g) for g in missing)

        logger.warning(
            "orchestrator: TIMEOUT %s — missing verdicts from %s after %d reminders",
            request_id, missing, MAX_RETRIES,
        )
        await tools.send_message(
            f"⚠️ **Pipeline TIMEOUT** — `{request_id}`\n\n"
            f"Did not receive verdict(s) from: **{missing_display}** "
            f"after {MAX_RETRIES} reminders ({MAX_RETRIES * RETRY_INTERVAL} s).\n\n"
            "Escalating to **Head of Digital Assets** for manual review.\n"
            "No automated seal.",
            mentions=[initiator],
        )
        await tools.send_event(
            content=f"orchestrator_result:{request_id}",
            message_type="tool_result",
            metadata={
                "agent":            "orchestrator",
                "request_id":       request_id,
                "status":           "timeout_incomplete",
                "missing_agents":   missing,
                "arrived_verdicts": arrived,
                "reminders_sent":   MAX_RETRIES,
            },
        )
        self._write_band_result(case, request_id)

    # ── Verdict collection ─────────────────────────────────────────────────────

    async def _collect_verdict(
        self,
        msg: PlatformMessage,
        tools: AgentToolsProtocol,
        room_id: str,
        content: str,
        sender: str,
    ) -> None:
        # Identify which specialist sent this — UUID lookup, then display-name fallback.
        agent_name = self._agent_id_map.get(sender) or _AGENT_NAME_MAP.get(
            msg.sender_name or ""
        )
        if agent_name is None:
            logger.debug("orchestrator: unknown agent sender_id=%s — ignoring", sender)
            return

        req = _REQ_ID_RE.search(content)
        if not req:
            return  # agent message without a REQ-id — not a verdict

        request_id = req.group(1).upper()
        case_key   = (room_id, request_id)
        case       = self._cases.get(case_key)
        if case is None:
            logger.debug(
                "orchestrator: agent %s reply for unknown case %s — ignoring",
                agent_name, request_id,
            )
            return

        initiator = case["initiator"]
        state     = case["state"]

        # ── Stage-1 verdict ────────────────────────────────────────────────────
        if state == "awaiting_stage1" and agent_name in _STAGE1_GATES:
            if case["verdicts"].get(agent_name) is not None:
                logger.debug(
                    "orchestrator: duplicate verdict from %s for %s — ignoring",
                    agent_name, request_id,
                )
                return

            verdict = _parse_verdict(content)
            if verdict is None:
                logger.warning(
                    "orchestrator: no parseable verdict from %s for %s: %r",
                    agent_name, request_id, content[:200],
                )
                return

            case["verdicts"][agent_name]  = verdict
            case["summaries"][agent_name] = content[:300]
            collected = sum(1 for v in case["verdicts"].values() if v is not None)
            logger.info(
                "orchestrator: collected %s=%s for %s (%d/%d)",
                agent_name, verdict, request_id, collected, len(_STAGE1_GATES),
            )

            if collected < len(_STAGE1_GATES):
                remaining = [g for g in _STAGE1_GATES if case["verdicts"].get(g) is None]
                logger.info("orchestrator: %s still missing: %s", request_id, remaining)
                return

            # All 4 collected — cancel the chase task then evaluate the gate.
            logger.info("orchestrator: %s all 4 verdicts collected → applying gate", request_id)
            chase = case.get("chase_task")
            if chase and not chase.done():
                chase.cancel()
                logger.debug("orchestrator: chase task cancelled for %s", request_id)

            await self._apply_gate(tools, case_key, case, request_id, initiator)

        # ── Tokenizer verdict → ECDSA seal (Consensus Signer step) ───────────────
        elif state == "awaiting_tokenizer" and agent_name == "asset_tokenizer":
            token_verdict = _parse_verdict(content)
            if token_verdict is None:
                logger.info(
                    "orchestrator: %s tokenizer status message (no verdict yet) — ignoring, still waiting",
                    request_id,
                )
                return
            case["verdicts"]["asset_tokenizer"]  = token_verdict
            case["summaries"]["asset_tokenizer"] = content[:300]
            case["state"] = "complete"
            logger.info(
                "orchestrator: %s tokenizer=%s → running ConsensusSigner.seal()",
                request_id, token_verdict,
            )

            # Build case_record from non-PII client metadata.
            client = _CLIENT_INDEX.get(request_id, {})
            case_record: dict[str, Any] = {
                "request_id":      request_id,
                "client_id":       client.get("client_id"),
                "asset_type":      client.get("asset_type"),
                "asset_value_eur": client.get("asset_value_eur"),
                "submitted_at":    client.get("submitted_at"),
            }

            # Build agent_verdicts from structured state — no chat-text re-parsing.
            v     = case["verdicts"]
            summs = case["summaries"]
            agent_verdicts: dict[str, dict] = {
                "doc_auditor":        {"verdict": v["doc_auditor"],        "summary": summs.get("doc_auditor", "")},
                "kyc_guardian":       {"verdict": v["kyc_guardian"],       "summary": summs.get("kyc_guardian", "")},
                "dynamic_compliance": {"verdict": v["dynamic_compliance"], "summary": summs.get("dynamic_compliance", "")},
                "stress_test":        {"verdict": v["stress_test"],        "summary": summs.get("stress_test", "")},
                "asset_tokenizer":    {"verdict": token_verdict,           "summary": summs.get("asset_tokenizer", "")},
            }

            seal = await asyncio.to_thread(seal_decision, case_record, agent_verdicts)
            case["seal_result"]     = seal
            case["pipeline_status"] = (
                "approved_pending_human" if seal["status"] == "sealed" else "blocked_gate"
            )

            if seal["status"] == "sealed":
                sig_preview = seal["signature"][:16] + "…"
                await tools.send_message(
                    f"**Consensus Signer** — SEALED `{request_id}`\n"
                    f"Hash: `{seal['canonical_hash'][:20]}…`\n"
                    f"Signature: `{sig_preview}` · Curve: {seal['curve']}\n"
                    f"Gates cleared: {', '.join(seal['gates_cleared'])}\n"
                    f"Sealed at: {seal['sealed_at']}\n\n"
                    "Status: **approved_pending_human** — ready for the Head of "
                    "Digital Assets to review and sign.",
                    mentions=[initiator],
                )
                await tools.send_event(
                    content=f"consensus_seal:{request_id}",
                    message_type="tool_result",
                    metadata={
                        "agent":         "consensus_signer",
                        "request_id":    request_id,
                        "status":        "approved_pending_human",
                        "seal_hash":     seal["canonical_hash"],
                        "signature":     seal["signature"],
                        "public_key":    seal["public_key"],
                        "curve":         seal["curve"],
                        "gates_cleared": seal["gates_cleared"],
                        "sealed_at":     seal["sealed_at"],
                    },
                )
                logger.info(
                    "orchestrator: %s → SEALED (approved_pending_human) hash=%s…",
                    request_id, seal["canonical_hash"][:16],
                )
            else:
                await tools.send_message(
                    f"**Consensus Signer** — SEAL BLOCKED `{request_id}`\n"
                    f"Failed gate: **{seal['failed_gate']}**\n"
                    f"{seal['reason']}\n\n"
                    "Status: **blocked_gate** — token structure is visible above; "
                    "no cryptographic seal was produced.",
                    mentions=[initiator],
                )
                await tools.send_event(
                    content=f"consensus_seal:{request_id}",
                    message_type="tool_result",
                    metadata={
                        "agent":       "consensus_signer",
                        "request_id":  request_id,
                        "status":      "blocked_gate",
                        "failed_gate": seal["failed_gate"],
                        "reason":      seal["reason"],
                    },
                )
                logger.info(
                    "orchestrator: %s → SEAL BLOCKED gate=%s",
                    request_id, seal["failed_gate"],
                )

            # Persist canonical result for band_bridge to consume.
            self._write_band_result(case, request_id)

    # ── Gate evaluation ────────────────────────────────────────────────────────

    async def _apply_gate(
        self,
        tools: AgentToolsProtocol,
        case_key: tuple[str, str],
        case: dict,
        request_id: str,
        initiator: str,
    ) -> None:
        """All 4 stage-1 verdicts in — evaluate the governance gate."""
        v = case["verdicts"]

        doc_r    = {"verdict": v["doc_auditor"]}
        kyc_r    = {"verdict": v["kyc_guardian"], "summary": ""}
        comp_r   = {"verdict": v["dynamic_compliance"]}
        stress_r = {"verdict": v["stress_test"]}

        gate_outcome, gate_reason = evaluate_governance_gate(
            doc_r, kyc_r, comp_r, stress_r
        )
        case["gate_outcome"] = gate_outcome
        case["gate_reason"]  = gate_reason

        def fv(key: str) -> str:
            return (v.get(key) or "?").upper()

        await tools.send_message(
            f"**Stage 1 complete** — all 4 verdicts received for `{request_id}`\n"
            f"- Doc Auditor: **{fv('doc_auditor')}**\n"
            f"- KYC Guardian: **{fv('kyc_guardian')}**\n"
            f"- Dynamic Compliance: **{fv('dynamic_compliance')}**\n"
            f"- Stress-Test: **{fv('stress_test')}** *(advisory)*\n"
            f"\nGate: **{gate_outcome.upper()}** — {gate_reason}",
            mentions=[initiator],
        )

        # ── Hard stop ──────────────────────────────────────────────────────────
        if gate_outcome in ("halt", "blocked"):
            status = "halted_kyc" if gate_outcome == "halt" else "blocked_gate"
            icon   = "🚨" if gate_outcome == "halt" else "🔴"
            case["state"]           = "complete"
            case["pipeline_status"] = status
            case["seal_result"]     = {
                "status":     "blocked",
                "failed_gate": "kyc_guardian" if gate_outcome == "halt" else "governance_gate",
                "reason":     gate_reason,
            }
            await tools.send_message(
                f"{icon} **Pipeline {gate_outcome.upper()}** — `{request_id}`\n"
                f"No tokenization. No seal.\n"
                f"Reason: {gate_reason}",
                mentions=[initiator],
            )
            await tools.send_event(
                content=f"orchestrator_result:{request_id}",
                message_type="tool_result",
                metadata={
                    "agent":           "orchestrator",
                    "request_id":      request_id,
                    "status":          status,
                    "gate_outcome":    gate_outcome,
                    "stage1_verdicts": {k: v[k] for k in _STAGE1_GATES},
                    "reason":          gate_reason,
                },
            )
            logger.info("orchestrator: %s → %s", request_id, status)
            self._write_band_result(case, request_id)
            return

        # ── Gates clear → delegate to Asset Tokenizer ─────────────────────────
        case["state"] = "awaiting_tokenizer"
        token_mentions = [m for m in [initiator, self._token_id] if m]
        await tools.send_message(
            f"All mandatory gates cleared for `{request_id}`.\n\n"
            "@Asset Tokenizer — please design the token structure for "
            f"`{request_id}`.",
            mentions=token_mentions or [initiator],
        )
        logger.info("orchestrator: %s → delegating to Asset Tokenizer", request_id)

    # ── Result persistence (IPC to band_bridge) ────────────────────────────────

    def _write_band_result(self, case: dict, request_id: str) -> None:
        """
        Build the canonical (decision_record, event_log) and write it to
        database/band_results/{request_id}.json for band_bridge to consume.

        Called at every terminal case state: sealed, blocked, halted, timeout.
        The Band path produces a reduced agent_results dict (verdict + summary
        only) — the evidence package is structurally valid but less granular
        than the in-process path which carries model_used, latency_ms, etc.
        """
        v     = case["verdicts"]
        summs = case["summaries"]

        agent_results: dict[str, dict | None] = {}
        for gate in _STAGE1_GATES:
            if v.get(gate) is not None:
                agent_results[gate] = {
                    "verdict": v[gate],
                    "summary": summs.get(gate, ""),
                }
        if v.get("asset_tokenizer") is not None:
            agent_results["asset_tokenizer"] = {
                "verdict": v["asset_tokenizer"],
                "summary": summs.get("asset_tokenizer", ""),
            }

        decision_record, event_log = build_decision_record(
            request_id     = request_id,
            pipeline_status= case.get("pipeline_status") or "error",
            gate_outcome   = case.get("gate_outcome")    or "unknown",
            gate_reason    = case.get("gate_reason")     or "",
            agent_results  = agent_results,
            seal           = case.get("seal_result")     or {},
            briefing       = {},
            timings        = {"stage1_wall_ms": 0, "total_wall_ms": 0},
        )

        case["result"] = {"decision_record": decision_record, "event_log": event_log}

        _BAND_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_path = _BAND_RESULTS_DIR / f"{request_id}.json"
        result_path.write_text(
            json.dumps(
                {"decision_record": decision_record, "event_log": event_log},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        logger.info("orchestrator: band result written for %s → %s", request_id, result_path)
