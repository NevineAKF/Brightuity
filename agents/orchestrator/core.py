"""
agents/orchestrator/core.py
Brightuity — Canonical gate logic, seal, and record builder.

Single source of truth for the three functions both execution paths must call
identically:

    evaluate_governance_gate  — deterministic Layer-1 gate enforcement
    seal_decision             — ECDSA seal via the module-level ConsensusSigner
    build_decision_record     — canonical (decision_record, event_log) builder

Pure module: only imports ConsensusSigner. No HTTP, no Band, no FastAPI,
no logging of business data.

Both callers (in-process orchestrator and Band adapter) import from here.
Structural drift between the two paths is now impossible — there is one
implementation, not two.
"""

from __future__ import annotations

from agents.consensus_signer.logic import ConsensusSigner

# ── Stage-1 agent order (doc only, no asset_tokenizer — that is stage 2) ──────
# Referenced by build_decision_record's synthetic event_log.
_STAGE1_AGENTS: tuple[str, ...] = (
    "doc_auditor",
    "kyc_guardian",
    "dynamic_compliance",
    "stress_test",
)

# ── Module-level signer — one instance per process ────────────────────────────
# Ephemeral SECP256K1 keypair, stable for the duration of a process.
# In production: replace with an HSM-backed persistent key.
_signer = ConsensusSigner()


# ── Gate logic ─────────────────────────────────────────────────────────────────

def evaluate_governance_gate(
    doc_result:        dict,
    kyc_result:        dict,
    compliance_result: dict,
    stress_result:     dict,
) -> tuple[str, str]:
    """
    Enforce the hard governance gates deterministically.

    This function is the single point of gate logic. It is pure, side-effect-free,
    and testable in isolation. Any change to gate semantics happens here and nowhere
    else.

    KYC Guardian has absolute veto: a "halt" verdict stops the pipeline
    immediately, regardless of other verdicts. This is the hardest gate because
    KYC/AML obligations are binary legal requirements — there is no "partially
    compliant" path.

    Mandatory gates (ALL must be "pass" to proceed to tokenization):
      - Doc Auditor
      - KYC Guardian
      - Dynamic Compliance

    Advisory gate (NOT a hard-block at orchestrator level):
      - Stress-Test Simulator: a non-passing result is surfaced to the human but
        does not prevent the tokenizer from running. The human sees the full picture
        (token structure + risk assessment) and makes the final call.
        NOTE: the Consensus Signer still requires stress_test="pass" to produce a
        seal. So a stress_test fail ultimately results in "blocked_gate" status —
        but with a token structure visible, unlike the doc/kyc/compliance fail path.

    Returns:
        (gate_outcome, deciding_reason)
        gate_outcome: "halt" | "blocked" | "pass"
    """
    # ── Hard veto: KYC halt ────────────────────────────────────────────────────
    if kyc_result.get("verdict") == "halt":
        return "halt", (
            "KYC Guardian issued HALT verdict — immediate hard stop. "
            f"No tokenization. No seal. "
            f"Summary: {kyc_result.get('summary', '(no summary)')[:200]}"
        )

    # ── Collect mandatory gate failures ───────────────────────────────────────
    failures: list[str] = []
    if doc_result.get("verdict") != "pass":
        failures.append(
            f"doc_auditor={doc_result.get('verdict')!r}"
        )
    if kyc_result.get("verdict") != "pass":
        failures.append(
            f"kyc_guardian={kyc_result.get('verdict')!r}"
        )
    if compliance_result.get("verdict") != "pass":
        failures.append(
            f"dynamic_compliance={compliance_result.get('verdict')!r}"
        )
    # stress_test is intentionally excluded here — see module docstring for rationale.

    if failures:
        return "blocked", "Mandatory gate failures: " + "; ".join(failures)

    # Mention stress_test status in the pass reason so it's visible in the event log.
    stress_verdict = stress_result.get("verdict", "unknown")
    stress_note = (
        f"Stress-test={stress_verdict!r} (advisory — "
        "ConsensusSigner will enforce this gate at seal time)"
        if stress_verdict != "pass"
        else "Stress-test=pass"
    )
    return "pass", f"All mandatory gates cleared (Doc✓ KYC✓ Compliance✓). {stress_note}."


# ── Seal ───────────────────────────────────────────────────────────────────────

def seal_decision(case_record: dict, agent_verdicts: dict) -> dict:
    """
    Run the ECDSA seal step via the module-level ConsensusSigner.

    Wraps _signer.seal() so neither caller holds its own ConsensusSigner
    instance. Both execution paths call this function; the seal result is
    therefore structurally identical regardless of caller.

    Args:
        case_record:    Non-PII case metadata (request_id, client_id,
                        asset_type, asset_value_eur, submitted_at).
        agent_verdicts: Dict of verdict dicts keyed by agent name.

    Returns:
        SealedProof dict  (status="sealed")   — all 5 gates cleared.
        BlockedResult dict (status="blocked") — one or more gates failed.
    """
    return _signer.seal(case_record, agent_verdicts)


# ── Record builder ─────────────────────────────────────────────────────────────

def build_decision_record(
    request_id:      str,
    pipeline_status: str,
    gate_outcome:    str,
    gate_reason:     str,
    agent_results:   dict[str, dict | None],
    seal:            dict,
    briefing:        dict,
    timings:         dict,
) -> tuple[dict, list[dict]]:
    """
    Build the canonical (decision_record, event_log) pair from completed pipeline data.

    Shared by BOTH execution paths:
      in-process  → agents/orchestrator/orchestrator.py  (run_pipeline)
      Band-coord  → band_agents/orchestrator_adapter.py  (_write_band_result)

    run_pipeline ignores the synthetic event_log returned here and uses its own
    fine-grained _emit() log instead. The Band path uses the synthetic log.
    assemble_evidence_package reads event_log only for decision_lineage and never
    re-derives verdicts from events, so both logs are equally valid.

    Args:
        request_id:      Case identifier.
        pipeline_status: "approved_pending_human" | "halted_kyc" | "blocked_gate" | "error"
        gate_outcome:    "pass" | "blocked" | "halt" | "unknown"
        gate_reason:     Human-readable gate reason string.
        agent_results:   Dict keyed by agent name; value is full verdict dict or None.
        seal:            ConsensusSigner result — SealedProof or BlockedResult dict.
        briefing:        Layer-2 synthesis briefing dict (pass {} for no synthesis).
        timings:         {"stage1_wall_ms": int, "total_wall_ms": int}

    Returns:
        (decision_record, synthetic_event_log)
    """
    stage1_ms: int = timings.get("stage1_wall_ms", 0)
    total_ms:  int = timings.get("total_wall_ms",  0)
    token = agent_results.get("asset_tokenizer")

    decision_record: dict = {
        "request_id":      request_id,
        "pipeline_status": pipeline_status,
        "gate_outcome":    gate_outcome,
        "gate_reason":     gate_reason,
        "agents": {
            "doc_auditor":        agent_results.get("doc_auditor"),
            "kyc_guardian":       agent_results.get("kyc_guardian"),
            "dynamic_compliance": agent_results.get("dynamic_compliance"),
            "stress_test":        agent_results.get("stress_test"),
            "asset_tokenizer":    token,
        },
        "token_structure": token,
        "seal":            seal,
        "briefing":        briefing,
        "stage1_wall_ms":  stage1_ms,
        "total_wall_ms":   total_ms,
    }

    # Synthetic event_log — same schema as the in-process _emit() log, reconstructed
    # from final result state rather than recorded incrementally.
    evts: list[dict] = [
        {"event": "pipeline_start", "request_id": request_id, "timestamp_ms": 0},
        {"event": "stage1_start",   "request_id": request_id, "timestamp_ms": 1,
         "parallel_agents": list(_STAGE1_AGENTS)},
    ]
    for gate in _STAGE1_AGENTS:
        r = agent_results.get(gate)
        if r:
            evts.append({
                "event":         "agent_complete",
                "request_id":    request_id,
                "timestamp_ms":  0,
                "agent":         gate,
                "verdict":       r.get("verdict"),
                "model_used":    r.get("model_used"),
                "was_fallback":  r.get("was_fallback"),
                "latency_ms":    r.get("latency_ms"),
                "had_exception": False,
            })
    evts += [
        {"event": "stage1_complete", "request_id": request_id,
         "timestamp_ms": stage1_ms, "wall_ms": stage1_ms},
        {"event": "gate_result", "request_id": request_id,
         "timestamp_ms": stage1_ms, "outcome": gate_outcome, "reason": gate_reason},
    ]
    if token is not None:
        evts += [
            {"event": "stage2_start", "request_id": request_id,
             "timestamp_ms": stage1_ms, "agent": "asset_tokenizer"},
            {"event": "agent_complete", "request_id": request_id,
             "timestamp_ms": stage1_ms, "agent": "asset_tokenizer",
             "verdict": token.get("verdict"), "model_used": token.get("model_used"),
             "was_fallback": token.get("was_fallback"), "latency_ms": token.get("latency_ms"),
             "had_exception": False},
        ]
    else:
        evts.append({"event": "stage2_skip", "request_id": request_id,
                     "timestamp_ms": stage1_ms, "gate_outcome": gate_outcome})
    evts += [
        {"event": "stage3_start",   "request_id": request_id,
         "timestamp_ms": total_ms,  "agent": "consensus_signer"},
        {"event": "seal_complete",  "request_id": request_id,
         "timestamp_ms": total_ms,
         "status":          seal.get("status"),
         "failed_gate":     seal.get("failed_gate"),
         "canonical_hash":  seal.get("canonical_hash")},
        {"event": "pipeline_complete", "request_id": request_id,
         "timestamp_ms": total_ms,
         "pipeline_status": pipeline_status, "total_wall_ms": total_ms},
    ]
    if briefing:
        evts.append({"event": "briefing_complete", "request_id": request_id,
                     "timestamp_ms": total_ms,
                     "source": briefing.get("source"),
                     "model_used": briefing.get("model_used")})

    return decision_record, evts
