"""
band_agents/orchestrator_adapter.py  (Phase 2h — Band coordination + ECDSA seal)
Brightuity — Orchestrator Band adapter.

COORDINATION PATTERN (real Band, no in-process calls):
  1. Human @mentions "@Orchestrator REQ-xxxx"
     → Orchestrator posts ONE message @mentioning all 4 stage-1 agents by UUID.
     → Their adapters receive it, run their engines, reply in the room.
  2. Each specialist's send_message reply arrives in on_message as a MessageEvent
     (msg.sender_type="Agent", msg.sender_id=<specialist UUID>).
     → Orchestrator parses the verdict from msg.content (always contains **PASS**,
       **FAIL**, or **HALT** in bold) and stores it in per-room+request state.
  3. When all 4 stage-1 verdicts are collected → _evaluate_governance_gate:
     - halt/blocked → post stop message + send_event, case complete.
     - pass → @mention Asset Tokenizer with the same REQ-id.
  4. Tokenizer reply arrives → Orchestrator runs ConsensusSigner.seal() in-process
     on the structured verdicts already held in case state (no chat-text re-parsing),
     then posts the ECDSA seal result labeled as the Consensus Signer step.

STATE: self._cases[(room_id, request_id)] — persists across on_message() calls.
       asyncio is single-threaded; no locks needed for in-memory dict ops.

GATE LOGIC: _evaluate_governance_gate() — identical to
            agents/orchestrator/orchestrator.py:_evaluate_governance_gate.
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

from agents.consensus_signer.logic import ConsensusSigner

logger = logging.getLogger(__name__)

_CLIENTS_JSON = Path(__file__).parent.parent / "database" / "brightuity_clients.json"


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

# Display-name fallback: Band sender_name → internal gate key.
# Used when sender_id isn't found in _agent_id_map (e.g. env mismatch).
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


def _evaluate_governance_gate(
    doc_result: dict,
    kyc_result: dict,
    compliance_result: dict,
    stress_result: dict,
) -> tuple[str, str]:
    """
    Deterministic governance gate — identical logic to
    agents/orchestrator/orchestrator.py:_evaluate_governance_gate.

    KYC "halt" = absolute veto (no tokenizer, no seal).
    Doc / KYC (non-halt) / Compliance non-pass = "blocked" (no tokenizer).
    Stress-test is advisory; ConsensusSigner enforces it at seal time.

    Returns (gate_outcome, deciding_reason).
    gate_outcome: "halt" | "blocked" | "pass"
    """
    if kyc_result.get("verdict") == "halt":
        return "halt", (
            "KYC Guardian issued HALT verdict — immediate hard stop. "
            f"Summary: {kyc_result.get('summary', '')[:200]}"
        )

    failures: list[str] = []
    if doc_result.get("verdict") != "pass":
        failures.append(f"doc_auditor={doc_result.get('verdict')!r}")
    if kyc_result.get("verdict") != "pass":
        failures.append(f"kyc_guardian={kyc_result.get('verdict')!r}")
    if compliance_result.get("verdict") != "pass":
        failures.append(f"dynamic_compliance={compliance_result.get('verdict')!r}")

    if failures:
        return "blocked", "Mandatory gate failures: " + "; ".join(failures)

    stress_verdict = stress_result.get("verdict", "unknown")
    stress_note = (
        f"Stress-test={stress_verdict!r} (advisory — ConsensusSigner enforces at seal)"
        if stress_verdict != "pass"
        else "Stress-test=pass"
    )
    return "pass", f"All mandatory gates cleared (Doc✓ KYC✓ Compliance✓). {stress_note}."


class OrchestratorAdapter(SimpleAdapter[list]):  # type: ignore[type-arg]
    """
    Band coordination adapter for the Orchestrator agent.

    Stateful across on_message() calls: self._cases holds per-room+request
    pipeline state so that specialist verdicts arriving in separate messages
    can be accumulated until the gate can be evaluated.
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

        # One ConsensusSigner per process — stable ephemeral keypair for the session.
        self._signer = ConsensusSigner()

        # Per-(room_id, request_id) pipeline state.
        # {
        #   "initiator": str,   # human sender_id — used for all reply mentions
        #   "state": "awaiting_stage1" | "awaiting_tokenizer" | "complete",
        #   "verdicts":  {gate_key: "pass"|"fail"|"halt"|None, ...},
        #   "summaries": {gate_key: str},  # first ~300 chars of agent's reply (for seal)
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

        # Initialise
        self._cases[case_key] = {
            "initiator": sender,
            "state":     "awaiting_stage1",
            "verdicts":  {k: None for k in _STAGE1_GATES},
            "summaries": {},
        }
        logger.info("orchestrator: NEW CASE %s room=%s", request_id, room_id)

        # Post ONE message @mentioning all 4 stage-1 agents (by UUID).
        # Their adapters receive this, parse the REQ-id, run their engines,
        # and reply in the room — the same flow as when a human @mentions them.
        stage1_ids = [
            i for i in [self._doc_id, self._kyc_id, self._comp_id, self._stress_id]
            if i
        ]
        await tools.send_message(
            f"**Orchestrator** — coordinating compliance review for `{request_id}`.\n\n"
            "@Doc Auditor @KYC Guardian @Dynamic Compliance @Stress-Test — "
            f"please report your verdicts for `{request_id}`.",
            mentions=[sender] + stage1_ids,
        )

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
                "orchestrator: %s → %s=%s (%d/%d collected)",
                request_id, agent_name, verdict, collected, len(_STAGE1_GATES),
            )

            if collected < len(_STAGE1_GATES):
                return  # still waiting for remaining agents

            await self._apply_gate(tools, case_key, case, request_id, initiator)

        # ── Tokenizer verdict → ECDSA seal (Consensus Signer step) ───────────────
        elif state == "awaiting_tokenizer" and agent_name == "asset_tokenizer":
            token_verdict = _parse_verdict(content)
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
            v        = case["verdicts"]
            summs    = case["summaries"]
            agent_verdicts: dict[str, dict] = {
                "doc_auditor":        {"verdict": v["doc_auditor"],        "summary": summs.get("doc_auditor", "")},
                "kyc_guardian":       {"verdict": v["kyc_guardian"],       "summary": summs.get("kyc_guardian", "")},
                "dynamic_compliance": {"verdict": v["dynamic_compliance"], "summary": summs.get("dynamic_compliance", "")},
                "stress_test":        {"verdict": v["stress_test"],        "summary": summs.get("stress_test", "")},
                "asset_tokenizer":    {"verdict": token_verdict,           "summary": summs.get("asset_tokenizer", "")},
            }

            seal = await asyncio.to_thread(self._signer.seal, case_record, agent_verdicts)

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

        gate_outcome, gate_reason = _evaluate_governance_gate(
            doc_r, kyc_r, comp_r, stress_r
        )

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
            case["state"] = "complete"
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
