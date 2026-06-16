"""
agents/orchestrator/orchestrator.py
Brightuity — Deterministic pipeline orchestrator.

NOT an LLM agent. Pure deterministic Python control flow. The intelligence
lives in the seven specialist agents; the control, governance enforcement, and
auditability live here in provable code.

Decision to NOT use CrewAI or any LLM for coordination:
  - Gate enforcement must be identical every run (no stochastic control flow).
  - The audit trail must be reproducible: same inputs → same gate decisions.
  - A judge picking any random client must get the exact same governance logic.
  - Band coordination is a communication layer; the decision logic is here.

Execution graph (DAG):

  ┌─────────────┐  ┌─────────────────┐  ┌──────────────────────┐  ┌────────────┐
  │ Doc Auditor │  │  KYC Guardian   │  │  Dynamic Compliance  │  │ Stress-Test│
  └──────┬──────┘  └────────┬────────┘  └──────────┬───────────┘  └─────┬──────┘
         └──────────────────┴──────────────────────┴──────────────────────┘
                              ↓  (ThreadPoolExecutor, parallel)
                    ┌─────────────────────┐
                    │  GOVERNANCE GATE    │  ← deterministic Python,
                    │  (mandatory check)  │    one clearly-named function
                    └──────────┬──────────┘
                               │
              ┌────────────────┴────────────────┐
              │ gate == "pass"                  │ gate == "halt" or "blocked"
              ↓                                  ↓
    ┌──────────────────┐              ┌──────────────────────┐
    │  Asset Tokenizer │              │  (tokenizer skipped) │
    └────────┬─────────┘              └──────────┬───────────┘
             └──────────────────────────────────┘
                               ↓  (always)
                    ┌──────────────────────┐
                    │  Consensus Signer    │  ← ECDSA seal if all 5 gates pass,
                    │  (seal or block)     │    BlockedResult otherwise
                    └──────────────────────┘

Dual-layer gate system (deliberate design):
  Layer 1 — Orchestrator (evaluate_governance_gate from core):
    Mandatory hard-blockers: Doc Auditor, KYC Guardian, Dynamic Compliance.
    KYC "halt" triggers immediate hard stop (no tokenizer).
    Other failures block tokenizer (gate="blocked").

    Advisory (non-blocking at orchestrator level): Stress-Test Simulator.
    Rationale: risk assessment is context-dependent; the Head of Digital Assets
    may accept elevated risk with explicit conditions. KYC/AML and regulatory
    compliance, by contrast, are binary legal requirements.
    When stress_test returns "fail", the tokenizer STILL runs so the human
    sees the proposed structure alongside the risk report — full picture, not
    a blind block.

  Layer 2 — Consensus Signer (ConsensusSigner.seal):
    Requires ALL FIVE mandatory gates to return "pass" before producing a seal.
    This includes stress_test. A stress_test "fail" → seal blocked → status
    "blocked_gate". The tokenizer result (from Layer 1 pass) is still visible.
    Consequence: stress_test fail → tokenizer ran → seal blocked → human sees
    both the proposed structure AND the risk verdict. Informed decision.

Pipeline status values:
  "approved_pending_human" — all 5 gates passed, seal succeeded, human decides.
  "halted_kyc"             — KYC Guardian issued "halt" (most severe: PEP/AML).
  "blocked_gate"           — one or more mandatory gates failed / seal blocked.
  "error"                  — unexpected pipeline failure (not a verdict).

Public interface:
    run_pipeline(client_record, *, _agent_overrides=None, _synthesis_override=None)
        -> tuple[dict, list[dict]]
    Returns (decision_record, event_log).
    decision_record["briefing"] is always present (LLM or templated fallback).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

from agents.doc_auditor.logic import audit_documents
from agents.kyc_guardian.logic import screen_kyc
from agents.dynamic_compliance.logic import assess_compliance
from agents.stress_test.logic import run_stress_test
from agents.asset_tokenizer.logic import design_token_structure
from agents.orchestrator.synthesis import synthesize_briefing
from agents.orchestrator.core import (
    evaluate_governance_gate,
    seal_decision,
    build_decision_record,
)
from shared.config import AGENT_HTTP_URLS

logger = logging.getLogger(__name__)


# ── HTTP transport helpers (used when AGENT_TRANSPORT=http) ────────────────────

def _http_call(agent_name: str, client_record: dict) -> dict:
    """
    Call a remote agent's POST /run endpoint and return its verdict dict.

    Used when AGENT_TRANSPORT=http. On any network or HTTP error the exception
    propagates to _safe_call, which catches it and applies the same conservative
    safe default as for in-process exceptions — kyc_guardian defaults to "halt",
    all others to "fail". No special handling needed here.

    Timeout is 180s — covers the slowest models (Gemini 2.5 Pro thinking, ~24s
    measured) with generous headroom. The caller's ThreadPoolExecutor is unaffected
    since this is a blocking sync call inside an already-threaded context.
    """
    url = AGENT_HTTP_URLS[agent_name]
    response = httpx.post(f"{url}/run", json=client_record, timeout=180.0)
    response.raise_for_status()
    return response.json()


def _make_http_agent(agent_name: str) -> Callable[[dict], dict]:
    """Return a callable matching the standard agent signature that calls over HTTP."""
    def _call(client_record: dict) -> dict:
        return _http_call(agent_name, client_record)
    return _call


# ── Pipeline status constants ──────────────────────────────────────────────────
STATUS_APPROVED_PENDING = "approved_pending_human"
STATUS_HALTED_KYC       = "halted_kyc"
STATUS_BLOCKED_GATE     = "blocked_gate"
STATUS_ERROR            = "error"

# Stage 1 agents run in parallel — order here is documentation only.
_STAGE1_AGENTS: tuple[str, ...] = (
    "doc_auditor",
    "kyc_guardian",
    "dynamic_compliance",
    "stress_test",
)


# ── Safe defaults on agent exception ───────────────────────────────────────────

def _safe_default(agent_name: str, error_detail: str) -> dict:
    """
    Conservative verdict dict returned when an agent raises an uncaught exception.

    KYC Guardian defaults to 'halt': an infrastructure failure must never silently
    pass a KYC gate. All other agents default to 'fail'. A field 'exception' is
    always present so callers can distinguish a genuine verdict from a safe default.
    """
    base: dict = {
        "agent":        agent_name,
        "model_used":   "none",
        "was_fallback": False,
        "latency_ms":   0,
        "exception":    error_detail,
    }
    if agent_name == "kyc_guardian":
        return {**base,
                "verdict":     "halt",
                "summary":     f"Agent exception — defaulting to halt. {error_detail}",
                "flags_raised": ["agent_exception"]}
    if agent_name == "doc_auditor":
        return {**base,
                "verdict":      "fail",
                "summary":      f"Agent exception — defaulting to fail. {error_detail}",
                "issues_found": ["agent_exception"]}
    if agent_name == "dynamic_compliance":
        return {**base,
                "verdict":      "fail",
                "summary":      f"Agent exception — defaulting to fail. {error_detail}",
                "jurisdiction": "unknown",
                "citations":    [],
                "concerns":     ["agent_exception"],
                "retrieved_k":  0}
    if agent_name == "stress_test":
        return {**base,
                "verdict":      "fail",
                "summary":      f"Agent exception — defaulting to fail. {error_detail}",
                "risk_level":   "critical",
                "risk_factors": ["agent_exception"]}
    if agent_name == "asset_tokenizer":
        return {**base,
                "verdict":             "fail",
                "summary":             f"Agent exception — defaulting to fail. {error_detail}",
                "token_standard":      "unknown",
                "total_tokens":        0,
                "value_per_token_eur": 0.0,
                "structure_notes":     ["agent_exception"]}
    return {**base, "verdict": "fail", "summary": f"Agent exception. {error_detail}"}


# ── Safe call wrapper ───────────────────────────────────────────────────────────

def _safe_call(agent_name: str, fn: Callable[[dict], dict], client_record: dict) -> dict:
    """
    Call an agent function and return its result, or a safe default on any exception.
    One agent raising must never crash the others running concurrently.
    """
    try:
        return fn(client_record)
    except Exception as exc:
        logger.error(
            "orchestrator: agent=%s raised — applying safe default. "
            "type=%s error=%s", agent_name, type(exc).__name__, exc, exc_info=True,
        )
        return _safe_default(agent_name, f"{type(exc).__name__}: {exc}")


# ── Stage 1: parallel agent execution ─────────────────────────────────────────

def _run_stage1(
    client_record: dict,
    agents:        dict[str, Callable],
    emit:          Callable,
) -> tuple[dict[str, dict], int]:
    """
    Run the four Stage-1 agents concurrently in a ThreadPoolExecutor.

    Agent functions are synchronous/blocking (they call external LLM APIs).
    Threads are the correct primitive here — asyncio would require rewriting
    all agent functions as coroutines. Four workers = one per agent.

    Returns:
        (results dict keyed by agent name, wall_ms for the entire stage)
    """
    emit("stage1_start", parallel_agents=list(_STAGE1_AGENTS))

    t_stage = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            name: executor.submit(_safe_call, name, agents[name], client_record)
            for name in _STAGE1_AGENTS
        }
        # Collect in deterministic pipeline order (futures complete concurrently,
        # but we retrieve in order so the event log is readable).
        results: dict[str, dict] = {
            name: futures[name].result()
            for name in _STAGE1_AGENTS
        }
    wall_ms = int((time.monotonic() - t_stage) * 1000)

    for name in _STAGE1_AGENTS:
        r = results[name]
        emit(
            "agent_complete",
            agent=name,
            verdict=r.get("verdict"),
            model_used=r.get("model_used"),
            was_fallback=r.get("was_fallback"),
            latency_ms=r.get("latency_ms"),
            had_exception="exception" in r,
        )

    emit("stage1_complete", wall_ms=wall_ms)
    return results, wall_ms


# ── Public interface ───────────────────────────────────────────────────────────

def run_pipeline(
    client_record: dict,
    *,
    _agent_overrides:     dict[str, Callable] | None = None,
    _synthesis_override:  Callable | None            = None,
) -> tuple[dict, list[dict]]:
    """
    Run the complete Brightuity tokenisation pipeline for one client record.

    Two-layer architecture:
      Layer 1 — deterministic Python: governance gates, parallel execution,
                ECDSA seal. The intelligence is in the specialist agents;
                the control is here in provable code with zero stochasticity.
      Layer 2 — LLM synthesis: Claude Opus 4.8 reads the completed,
                sealed decision_record and produces the human-readable
                briefing for the Head of Digital Assets. It describes what
                Layer 1 decided; it never influences it. If synthesis fails,
                a deterministic templated briefing is substituted.

    Args:
        client_record:
            Full client dict from the database (brightuity_clients.json or DB1).
        _agent_overrides:
            Optional dict of callable overrides keyed by agent name. Used by
            tests to inject mock functions instead of real LLM-backed agents.
            Any agent not present in the override dict uses the real function.
            For the consensus_signer key, the callable must have the signature:
                fn(case_record: dict, agent_verdicts: dict) -> dict
        _synthesis_override:
            Optional callable override for the Layer 2 synthesis step.
            Must have the signature: fn(decision_record: dict) -> dict
            Used by tests to inject a mock synthesizer instead of calling
            the real LLM. If None (default), synthesize_briefing() is used.

    Returns:
        (decision_record, event_log)

        decision_record — structured final decision:
            request_id:      str
            pipeline_status: "approved_pending_human" | "halted_kyc" |
                             "blocked_gate" | "error"
            gate_outcome:    "pass" | "blocked" | "halt" | "unknown"
            gate_reason:     str
            agents: {
                "doc_auditor":        dict  — always present
                "kyc_guardian":       dict  — always present
                "dynamic_compliance": dict  — always present
                "stress_test":        dict  — always present
                "asset_tokenizer":    dict | None — None if gate did not pass
            }
            token_structure: dict | None    — same as agents["asset_tokenizer"]
            seal:            dict | None    — SealedProof or BlockedResult
            briefing:        dict           — Layer 2 briefing (always present;
                                             source="llm" or "templated_fallback")
            stage1_wall_ms:  int            — parallel stage wall time (ms)
            total_wall_ms:   int            — end-to-end Layer 1 wall time (ms)

        event_log — list of dicts, one per pipeline transition:
            event:        str   — "pipeline_start" | "stage1_start" |
                                  "agent_complete" | "stage1_complete" |
                                  "gate_result" | "stage2_start" | "stage2_skip" |
                                  "agent_complete" (for tokenizer) |
                                  "stage3_start" | "seal_complete" |
                                  "pipeline_complete" | "briefing_complete" |
                                  "pipeline_error"
            request_id:   str
            timestamp_ms: int   — ms since pipeline start
            + event-specific fields (verdict, wall_ms, reason, etc.)
    """
    t0 = time.monotonic()
    events: list[dict[str, Any]] = []
    request_id: str = client_record.get("request_id", "UNKNOWN")

    def _emit(event: str, **kwargs: Any) -> None:
        entry: dict[str, Any] = {
            "event":        event,
            "request_id":   request_id,
            "timestamp_ms": int((time.monotonic() - t0) * 1000),
            **kwargs,
        }
        events.append(entry)
        logger.info("orchestrator: %s", entry)

    # ── Agent function table ───────────────────────────────────────────────────
    # Transport switch: read at call time so tests can set AGENT_TRANSPORT in
    # os.environ without restarting the process. _agent_overrides always win
    # over whichever transport is selected — the existing mock tests are untouched.
    _transport = os.getenv("AGENT_TRANSPORT", "inprocess")
    if _transport == "http":
        real_agents: dict[str, Callable] = {
            "doc_auditor":        _make_http_agent("doc_auditor"),
            "kyc_guardian":       _make_http_agent("kyc_guardian"),
            "dynamic_compliance": _make_http_agent("dynamic_compliance"),
            "stress_test":        _make_http_agent("stress_test"),
            "asset_tokenizer":    _make_http_agent("asset_tokenizer"),
            "consensus_signer":   seal_decision,
        }
    else:
        real_agents: dict[str, Callable] = {
            "doc_auditor":        audit_documents,
            "kyc_guardian":       screen_kyc,
            "dynamic_compliance": assess_compliance,
            "stress_test":        run_stress_test,
            "asset_tokenizer":    design_token_structure,
            "consensus_signer":   seal_decision,
        }
    agents: dict[str, Callable] = {**real_agents, **(_agent_overrides or {})}

    _emit("pipeline_start")
    logger.info("orchestrator: pipeline started for %s", request_id)

    try:
        # ── STAGE 1: four agents, parallel ────────────────────────────────────
        stage1_results, stage1_wall_ms = _run_stage1(client_record, agents, _emit)

        doc_result        = stage1_results["doc_auditor"]
        kyc_result        = stage1_results["kyc_guardian"]
        compliance_result = stage1_results["dynamic_compliance"]
        stress_result     = stage1_results["stress_test"]

        # ── GOVERNANCE GATE ───────────────────────────────────────────────────
        gate_outcome, gate_reason = evaluate_governance_gate(
            doc_result, kyc_result, compliance_result, stress_result
        )
        _emit("gate_result", outcome=gate_outcome, reason=gate_reason)
        logger.info(
            "orchestrator: gate=%s request_id=%s", gate_outcome, request_id
        )

        # ── STAGE 2: tokenizer — conditional on gate ──────────────────────────
        token_result: dict | None = None

        if gate_outcome == "pass":
            _emit("stage2_start", agent="asset_tokenizer")
            token_result = _safe_call(
                "asset_tokenizer", agents["asset_tokenizer"], client_record
            )
            _emit(
                "agent_complete",
                agent="asset_tokenizer",
                verdict=token_result.get("verdict"),
                model_used=token_result.get("model_used"),
                was_fallback=token_result.get("was_fallback"),
                latency_ms=token_result.get("latency_ms"),
                had_exception="exception" in token_result,
            )
        else:
            _emit(
                "stage2_skip",
                gate_outcome=gate_outcome,
                reason=(
                    "KYC halt — pipeline stopped before tokenization."
                    if gate_outcome == "halt"
                    else "Gate blocked — mandatory gate failure prevents tokenization."
                ),
            )
            logger.info(
                "orchestrator: stage2 skipped gate=%s request_id=%s",
                gate_outcome, request_id,
            )

        # ── STAGE 3: seal — always ─────────────────────────────────────────────
        _emit("stage3_start", agent="consensus_signer")

        all_agent_verdicts: dict[str, dict] = {
            "doc_auditor":        doc_result,
            "kyc_guardian":       kyc_result,
            "dynamic_compliance": compliance_result,
            "stress_test":        stress_result,
        }
        if token_result is not None:
            all_agent_verdicts["asset_tokenizer"] = token_result

        seal_fn = agents["consensus_signer"]
        try:
            seal_result: dict = seal_fn(client_record, all_agent_verdicts)
        except Exception as exc:
            logger.error(
                "orchestrator: consensus_signer raised — %s", exc, exc_info=True
            )
            seal_result = {
                "status":     "error",
                "request_id": request_id,
                "reason":     f"{type(exc).__name__}: {exc}",
                "sealed_at":  None,
            }

        _emit(
            "seal_complete",
            status=seal_result.get("status"),
            failed_gate=seal_result.get("failed_gate"),          # present on BlockedResult
            canonical_hash=seal_result.get("canonical_hash"),    # present on SealedProof
        )

        # ── Determine pipeline status ─────────────────────────────────────────
        if kyc_result.get("verdict") == "halt":
            pipeline_status = STATUS_HALTED_KYC
        elif seal_result.get("status") == "sealed":
            pipeline_status = STATUS_APPROVED_PENDING
        else:
            pipeline_status = STATUS_BLOCKED_GATE

        total_wall_ms = int((time.monotonic() - t0) * 1000)
        _emit(
            "pipeline_complete",
            pipeline_status=pipeline_status,
            total_wall_ms=total_wall_ms,
        )
        logger.info(
            "orchestrator: pipeline complete request_id=%s status=%s total_ms=%d",
            request_id, pipeline_status, total_wall_ms,
        )

        _agent_results: dict[str, dict | None] = {
            "doc_auditor":        doc_result,
            "kyc_guardian":       kyc_result,
            "dynamic_compliance": compliance_result,
            "stress_test":        stress_result,
            "asset_tokenizer":    token_result,
        }

        # ── LAYER 2: LLM synthesis — additive, zero decision authority ─────────
        # Layer 1 (gates + seal) is COMPLETE and COMMITTED above this line.
        # synthesize_briefing receives the complete Layer-1 record (same fields
        # as the final decision_record, minus briefing) so it can describe the
        # decision — it never influences it.
        _synthesize = _synthesis_override if _synthesis_override is not None else synthesize_briefing
        _pre_brief: dict = {
            "request_id":      request_id,
            "pipeline_status": pipeline_status,
            "gate_outcome":    gate_outcome,
            "gate_reason":     gate_reason,
            "agents":          _agent_results,
            "token_structure": token_result,
            "seal":            seal_result,
            "stage1_wall_ms":  stage1_wall_ms,
            "total_wall_ms":   total_wall_ms,
        }
        try:
            briefing = _synthesize(_pre_brief)
        except Exception as exc:
            logger.error(
                "orchestrator: synthesis raised unexpectedly for %s: %s",
                request_id, exc, exc_info=True,
            )
            briefing = {
                "headline":          f"[Briefing unavailable — synthesis error: {type(exc).__name__}]",
                "decisive_factor":   gate_reason,
                "per_agent_summary": [],
                "recommendation":    "Review the full decision record manually.",
                "source":            "error_fallback",
                "model_used":        "none",
                "was_fallback":      False,
                "latency_ms":        0,
            }
        _emit(
            "briefing_complete",
            source=briefing.get("source"),
            model_used=briefing.get("model_used"),
        )

        # Build canonical record via the shared builder so both execution paths
        # (in-process and Band-coord) produce the same shape. The fine-grained
        # _emit() event log is used for the returned tuple; the synthetic log
        # from build_decision_record is for the Band path only.
        decision_record, _synth_log = build_decision_record(
            request_id=request_id,
            pipeline_status=pipeline_status,
            gate_outcome=gate_outcome,
            gate_reason=gate_reason,
            agent_results=_agent_results,
            seal=seal_result,
            briefing=briefing,
            timings={"stage1_wall_ms": stage1_wall_ms, "total_wall_ms": total_wall_ms},
        )

        return decision_record, events

    except Exception as exc:
        total_wall_ms = int((time.monotonic() - t0) * 1000)
        _emit("pipeline_error", error=f"{type(exc).__name__}: {exc}",
              total_wall_ms=total_wall_ms)
        logger.error(
            "orchestrator: pipeline error for %s: %s", request_id, exc, exc_info=True
        )
        return {
            "request_id":      request_id,
            "pipeline_status": STATUS_ERROR,
            "gate_outcome":    "unknown",
            "gate_reason":     f"Pipeline error: {type(exc).__name__}: {exc}",
            "agents":          {},
            "token_structure": None,
            "seal":            None,
            "stage1_wall_ms":  0,
            "total_wall_ms":   total_wall_ms,
        }, events
