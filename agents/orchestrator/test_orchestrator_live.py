"""
agents/orchestrator/test_orchestrator_live.py
Brightuity — Full end-to-end pipeline live run. No mocks.

Runs the complete 7-agent Brightuity pipeline against a single real client
from the database. Everything is live: real LLM calls, real ECDSA seal, real
Opus 4.8 synthesis. This is the first real-world validation of the assembled
pipeline.

Client: Marcus Weber (REQ-2041)
  Commercial Property — Office building, Berlin — EUR 2,000,000
  KYC: clean, docs: complete, source: salary accumulation
  Expected outcome: APPROVE (clean baseline case)

What we are measuring (in priority order):
  1. stage1_wall_ms — real parallel latency of the 4 concurrent stage-1
     agents. This is the number we designed ThreadPoolExecutor for.
  2. total_wall_ms  — full Layer 1 wall time (seal complete, before synthesis).
  3. synthesis latency — Opus 4.8 briefing generation time.
  4. All model choices + was_fallback flags — confirms the engine picks
     the right model per agent and only falls over when needed.

Observations only — no hard verdict assertions on real model output.
Pipeline completion and coherence (seal matches gate) are checked.

Run:
    python -m agents.orchestrator.test_orchestrator_live
  or:
    python agents/orchestrator/test_orchestrator_live.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# ── UTF-8 output ───────────────────────────────────────────────────────────────
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# INFO logging → stdout so agent call logs stream in real time during the run.
# This lets the watcher see which model is attempting, retrying, or falling over
# before the final summary appears.
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
# Reduce noise from HTTP layer
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from agents.orchestrator.orchestrator import run_pipeline

# ── Output helpers ─────────────────────────────────────────────────────────────
_SEP  = "─" * 72
_SEP2 = "═" * 72

_DATA_FILE = Path(__file__).parent.parent.parent / "database" / "brightuity_clients.json"


def _load_client(request_id: str) -> dict:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    for client in data["clients"]:
        if client.get("request_id") == request_id:
            return client
    raise ValueError(f"Client {request_id!r} not found in {_DATA_FILE}")


def _ms(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1000:
        return f"{n:,}ms  ({n/1000:.1f}s)"
    return f"{n}ms"


def _verdict_icon(v: str | None) -> str:
    if v == "pass":   return "✓ PASS"
    if v == "fail":   return "✗ FAIL"
    if v == "halt":   return "⊘ HALT"
    return f"? {v}"


def _print_section(title: str) -> None:
    print()
    print(_SEP)
    print(f"  {title}")
    print(_SEP)


def _wrap(text: str, width: int = 65, indent: str = "    ") -> str:
    """Wrap a long string at word boundaries, indenting continuation lines."""
    if len(text) <= width:
        return text
    words = text.split()
    lines, line = [], []
    cur = 0
    for w in words:
        if cur + len(w) + (1 if line else 0) > width:
            lines.append(" ".join(line))
            line, cur = [w], len(w)
        else:
            line.append(w)
            cur += len(w) + (1 if line else 1)
    if line:
        lines.append(" ".join(line))
    return ("\n" + indent).join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print()
    print(_SEP2)
    print("  BRIGHTUITY · Full Pipeline · Live Run — NO MOCKS")
    print("  Real LLMs · Real ECDSA seal · Real Opus 4.8 synthesis")
    print(_SEP2)

    # ── Load client ────────────────────────────────────────────────────────────
    client = _load_client("REQ-2041")

    print()
    print("  CLIENT UNDER REVIEW")
    print(f"    Request ID   : {client['request_id']}")
    print(f"    Client ID    : {client['client_id']}")
    print(f"    Asset type   : {client['asset_type']}")
    print(f"    Asset detail : {client['asset_detail']}")
    print(f"    Asset value  : EUR {client['asset_value_eur']:,}")
    print(f"    Nationality  : {client['nationality']}")
    print(f"    Docs status  : {client['documents_status']}")
    print(f"    KYC status   : {client['kyc_status']}")
    print(f"    Risk flags   : {client.get('risk_flags', []) or 'none'}")
    print()
    print("  ⚠  Live run — models will be called now. This takes several minutes.")
    print("  ⚠  expected_outcome field is NOT passed to any agent (training label only).")
    print()
    print(_SEP2)
    print("  PIPELINE STARTING — agent logs stream below:")
    print(_SEP2)

    # ── Run pipeline ───────────────────────────────────────────────────────────
    wall_t0 = time.monotonic()
    decision, events = run_pipeline(client)
    wall_total = time.monotonic() - wall_t0

    # ── Stop log streaming, switch to structured output ────────────────────────
    print()
    print(_SEP2)
    print("  PIPELINE COMPLETE — structured results below:")
    print(_SEP2)

    # ── Stage 1 results ────────────────────────────────────────────────────────
    _print_section("STAGE 1 — PARALLEL AGENTS  (4 × concurrent)")

    stage1_agents = ("doc_auditor", "kyc_guardian", "dynamic_compliance", "stress_test")
    agent_labels  = {
        "doc_auditor":        "Doc Auditor",
        "kyc_guardian":       "KYC Guardian",
        "dynamic_compliance": "Dynamic Compliance",
        "stress_test":        "Stress-Test Simulator",
    }

    agents_dict = decision.get("agents", {})
    for key in stage1_agents:
        r = agents_dict.get(key) or {}
        label    = agent_labels[key]
        verdict  = r.get("verdict", "?")
        model    = r.get("model_used", "?")
        fb       = "YES ← FALLBACK" if r.get("was_fallback") else "no"
        lat      = r.get("latency_ms")
        exc      = r.get("exception")
        icon     = _verdict_icon(verdict)
        print(f"  {label:<24}  {icon}")
        print(f"    model_used   : {model}")
        print(f"    was_fallback : {fb}")
        print(f"    latency_ms   : {_ms(lat)}")
        if exc:
            print(f"    ⚠ EXCEPTION  : {exc}")
        if key == "doc_auditor" and r.get("issues_found"):
            print(f"    issues_found : {r['issues_found']}")
        if key == "kyc_guardian" and r.get("flags_raised"):
            print(f"    flags_raised : {r['flags_raised']}")
        if key == "dynamic_compliance":
            if r.get("concerns"):
                print(f"    concerns     : {r['concerns']}")
            if r.get("citations"):
                print(f"    citations    : {r['citations'][:2]}")
        if key == "stress_test":
            print(f"    risk_level   : {r.get('risk_level', '?')}")
            if r.get("risk_factors"):
                print(f"    risk_factors : {r['risk_factors'][:3]}")
        print(f"    summary      : {_wrap(r.get('summary', '—')[:200])}")
        print()

    stage1_ms = decision.get("stage1_wall_ms", 0)
    print(f"  ► stage1_wall_ms (parallel wall time): {_ms(stage1_ms)}")
    longest  = max((agents_dict.get(k) or {}).get("latency_ms") or 0 for k in stage1_agents)
    print(f"    longest single agent               : {_ms(longest)}")
    serial_est = sum((agents_dict.get(k) or {}).get("latency_ms") or 0 for k in stage1_agents)
    print(f"    serial estimate (sum of latencies) : {_ms(serial_est)}")
    if serial_est > 0:
        speedup = serial_est / stage1_ms if stage1_ms > 0 else float("inf")
        print(f"    effective speedup                  : {speedup:.1f}×")

    # ── Gate ──────────────────────────────────────────────────────────────────
    _print_section("GOVERNANCE GATE")

    gate_out    = decision.get("gate_outcome", "?")
    gate_reason = decision.get("gate_reason", "?")
    print(f"  gate_outcome : {gate_out}")
    print(f"  gate_reason  : {_wrap(gate_reason)}")

    # ── Stage 2 — tokenizer ────────────────────────────────────────────────────
    _print_section("STAGE 2 — ASSET TOKENIZER")

    token = decision.get("token_structure")
    if token is None:
        print(f"  Skipped — gate_outcome was '{gate_out}' (tokenizer only runs on gate='pass')")
    else:
        verdict = token.get("verdict", "?")
        print(f"  Verdict        : {_verdict_icon(verdict)}")
        print(f"  token_standard : {token.get('token_standard', '—')}")
        total  = token.get("total_tokens", 0)
        per_t  = token.get("value_per_token_eur", 0.0)
        implied = total * per_t
        print(f"  Structure      : {total:,} tokens × EUR {per_t:,.2f} = EUR {implied:,.0f}")
        asset_val = client.get("asset_value_eur", 0)
        if asset_val and implied:
            pct = abs(implied - asset_val) / asset_val * 100
            print(f"  Math check     : |implied - asset_value| / asset_value = {pct:.2f}%  "
                  f"({'OK ≤5%' if pct <= 5 else 'WARN >5%'})")
        for note in token.get("structure_notes", []):
            print(f"  note           : {_wrap(note)}")
        print(f"  model_used     : {token.get('model_used', '?')}")
        print(f"  was_fallback   : {'YES ← FALLBACK' if token.get('was_fallback') else 'no'}")
        print(f"  latency_ms     : {_ms(token.get('latency_ms'))}")
        print(f"  summary        : {_wrap(token.get('summary', '—')[:200])}")

    # ── Seal ──────────────────────────────────────────────────────────────────
    _print_section("SEAL  (ECDSA SECP256K1 — ConsensusSigner)")

    seal = decision.get("seal") or {}
    seal_status = seal.get("status", "?")
    print(f"  status         : {seal_status}")
    if seal_status == "sealed":
        chash = seal.get("canonical_hash", "")
        print(f"  canonical_hash : {chash}")
        print(f"  sealed_at      : {seal.get('sealed_at', '?')}")
        print(f"  curve          : {seal.get('curve', '?')}")
        gates_cleared = seal.get("gates_cleared", [])
        print(f"  gates_cleared  : {', '.join(gates_cleared)}")
        sig = seal.get("signature", "")
        print(f"  signature      : {sig[:32]}... ({len(sig)//2} bytes)")
        pub = seal.get("public_key", "")
        print(f"  public_key     : {pub[:16]}... (compressed, 33 bytes)")
    elif seal_status == "blocked":
        print(f"  failed_gate    : {seal.get('failed_gate', '?')}")
        print(f"  reason         : {_wrap(seal.get('reason', '?')[:200])}")
        print(f"  sealed_at      : None — no signature produced")

    # ── Layer 2 briefing ───────────────────────────────────────────────────────
    _print_section("LAYER 2 BRIEFING  (Claude Opus 4.8 → Sonnet 4.6 failover)")

    briefing = decision.get("briefing") or {}
    b_source  = briefing.get("source", "?")
    b_model   = briefing.get("model_used", "?")
    b_lat     = briefing.get("latency_ms", 0)
    b_fb      = briefing.get("was_fallback", False)

    print(f"  source         : {b_source}")
    print(f"  model_used     : {b_model}")
    print(f"  was_fallback   : {'YES ← SONNET CARRIED' if b_fb else 'no'}")
    print(f"  latency_ms     : {_ms(b_lat)}")
    print()

    headline = briefing.get("headline", "—")
    print(f"  HEADLINE:")
    print(f"    {_wrap(headline)}")
    print()

    dec_factor = briefing.get("decisive_factor", "—")
    print(f"  DECISIVE FACTOR:")
    print(f"    {_wrap(dec_factor)}")
    print()

    per_agent_sum = briefing.get("per_agent_summary", [])
    print(f"  PER-AGENT SUMMARY:")
    for line in per_agent_sum:
        print(f"    • {_wrap(line, width=63, indent='      ')}")
    print()

    recommendation = briefing.get("recommendation", "—")
    print(f"  RECOMMENDATION (to the Head of Digital Assets):")
    # Wrap recommendation at ~65 chars, indented
    words = recommendation.split()
    lines_out, cur_line, cur_len = [], [], 0
    for w in words:
        if cur_len + len(w) + (1 if cur_line else 0) > 65:
            lines_out.append("    " + " ".join(cur_line))
            cur_line, cur_len = [w], len(w)
        else:
            cur_line.append(w)
            cur_len += len(w) + (1 if cur_line else 1)
    if cur_line:
        lines_out.append("    " + " ".join(cur_line))
    print("\n".join(lines_out))

    # ── Event log summary ─────────────────────────────────────────────────────
    _print_section("PIPELINE EVENT LOG  (abbreviated)")

    for e in events:
        ev   = e.get("event", "?")
        ts   = e.get("timestamp_ms", 0)
        rest = {k: v for k, v in e.items()
                if k not in ("event", "request_id", "timestamp_ms")}
        # Format key fields concisely
        parts = []
        for k, v in rest.items():
            if v is None:
                continue
            if isinstance(v, bool):
                parts.append(f"{k}={v}")
            elif isinstance(v, str) and len(v) > 50:
                parts.append(f"{k}={v[:48]}…")
            elif isinstance(v, list):
                parts.append(f"{k}=[{len(v)} items]")
            else:
                parts.append(f"{k}={v}")
        detail = "  ".join(parts)
        print(f"  +{ts:>6}ms  {ev:<22}  {detail}")

    # ── End-to-end summary ────────────────────────────────────────────────────
    _print_section("END-TO-END METRICS")

    pipeline_status = decision.get("pipeline_status", "?")
    layer1_ms       = decision.get("total_wall_ms", 0)

    valid_statuses = {
        "approved_pending_human", "halted_kyc", "blocked_gate", "error"
    }
    status_ok   = pipeline_status in valid_statuses
    seal_ok     = (
        (seal_status == "sealed" and gate_out == "pass") or
        (seal_status == "blocked" and gate_out in ("halt", "blocked")) or
        (seal_status == "blocked")  # stress/tokenizer fail also blocks
    )
    briefing_ok = bool(briefing.get("headline"))

    print(f"  pipeline_status          : {pipeline_status}")
    print(f"  gate_outcome             : {gate_out}")
    print(f"  seal_status              : {seal_status}")
    print(f"  briefing_source          : {b_source}")
    print()
    print(f"  stage1_wall_ms (parallel): {_ms(stage1_ms)}")
    print(f"  layer1_total_ms (L1 only): {_ms(layer1_ms)}")
    print(f"  synthesis_latency_ms (L2): {_ms(b_lat)}")
    print(f"  full_wall_ms (L1+L2)     : {_ms(int(wall_total * 1000))}")
    print()

    # Coherence checks (soft — real models, observational run)
    icon_ok   = "✓"
    icon_fail = "✗"
    print(f"  Coherence checks (observational — not assertions on verdict quality):")
    print(f"  {icon_ok if status_ok   else icon_fail}  pipeline_status is a valid value  [{pipeline_status}]")
    print(f"  {icon_ok if seal_ok     else icon_fail}  seal is coherent with gate outcome  [seal={seal_status}, gate={gate_out}]")
    print(f"  {icon_ok if briefing_ok else icon_fail}  briefing was produced  [source={b_source}]")

    print()
    print(_SEP2)
    print("  Live run complete. Review the numbers above before proceeding.")
    print(_SEP2)
    print()
