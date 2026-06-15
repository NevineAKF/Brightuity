"""
agents/orchestrator/test_orchestrator_http_live.py
Brightuity -- Real HTTP end-to-end pipeline run.

Starts all 5 agent services as real uvicorn subprocesses, waits until each
/health endpoint returns ok, then runs Marcus Weber (REQ-2041) through the
orchestrator with AGENT_TRANSPORT=http. Everything is live: real uvicorn
servers, real LLM calls inside each service, real ECDSA seal, real Opus 4.8
synthesis. No mocks.

This is the smoke test that proves the HTTP transport path works end-to-end
before Band is added.

Services started (ports 8001-8005):
    doc_auditor        -> http://localhost:8001
    kyc_guardian       -> http://localhost:8002
    dynamic_compliance -> http://localhost:8003
    stress_test        -> http://localhost:8004
    asset_tokenizer    -> http://localhost:8005

Run:
    python -m agents.orchestrator.test_orchestrator_http_live
  or:
    python agents/orchestrator/test_orchestrator_http_live.py
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Project root on path (before any project imports) ─────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Load .env before starting subprocesses so they inherit API keys ───────────
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── UTF-8 console output ───────────────────────────────────────────────────────
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# INFO logging -> stdout so LLM call logs stream in real time.
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)

import httpx

# ── Service registry ───────────────────────────────────────────────────────────
_SERVICES: list[dict] = [
    {"name": "doc_auditor",        "port": 8001,
     "module": "agents.doc_auditor.service:app"},
    {"name": "kyc_guardian",       "port": 8002,
     "module": "agents.kyc_guardian.service:app"},
    {"name": "dynamic_compliance", "port": 8003,
     "module": "agents.dynamic_compliance.service:app"},
    {"name": "stress_test",        "port": 8004,
     "module": "agents.stress_test.service:app"},
    {"name": "asset_tokenizer",    "port": 8005,
     "module": "agents.asset_tokenizer.service:app"},
]

_DATA_FILE = ROOT / "database" / "brightuity_clients.json"


# ── Service lifecycle ──────────────────────────────────────────────────────────

def _start_services() -> list[subprocess.Popen]:
    """Launch all 5 agent services as background uvicorn processes."""
    procs: list[subprocess.Popen] = []
    for svc in _SERVICES:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             svc["module"],
             "--host", "0.0.0.0",
             "--port", str(svc["port"]),
             "--log-level", "warning"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ},    # inherit parent env (API keys from .env)
        )
        procs.append(proc)
        print(f"    started {svc['name']:<22} PID {proc.pid}  port {svc['port']}")
    return procs


def _wait_for_health(timeout_s: float = 60.0) -> None:
    """Poll each /health endpoint until it responds 200 or timeout expires."""
    print(f"\n  Waiting for all 5 services to be healthy (timeout {timeout_s:.0f}s)...")
    deadline = time.monotonic() + timeout_s
    for svc in _SERVICES:
        url = f"http://localhost:{svc['port']}/health"
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Service '{svc['name']}' did not become healthy "
                    f"within {timeout_s:.0f}s ({url})"
                )
            try:
                r = httpx.get(url, timeout=2.0)
                if r.status_code == 200:
                    data = r.json()
                    print(f"    {svc['name']:<22} -> {url}  status={data.get('status')}")
                    break
            except Exception:
                time.sleep(0.4)


def _stop_services(procs: list[subprocess.Popen]) -> None:
    """Terminate all service processes and wait for them to exit."""
    print("\n  Stopping services...")
    for proc, svc in zip(procs, _SERVICES):
        proc.terminate()
        print(f"    SIGTERM -> {svc['name']:<22} PID {proc.pid}")
    for proc, svc in zip(procs, _SERVICES):
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            print(f"    SIGKILL -> {svc['name']:<22} PID {proc.pid} (did not exit in 8s)")
    print("  All services stopped.")


# ── Client loader ──────────────────────────────────────────────────────────────

def _load_client(request_id: str) -> dict:
    data = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    for client in data["clients"]:
        if client.get("request_id") == request_id:
            return client
    raise ValueError(f"Client {request_id!r} not found in {_DATA_FILE}")


# ── Display helpers ────────────────────────────────────────────────────────────

def _ms(n: int | None) -> str:
    if n is None:
        return "--"
    return f"{n:,}ms  ({n/1000:.1f}s)" if n >= 1000 else f"{n}ms"


_SEP  = "-" * 72
_SEP2 = "=" * 72


def _print_agent(label: str, result: dict | None) -> None:
    if result is None:
        print(f"  {label:<26}: (skipped)")
        return
    icon = "PASS" if result.get("verdict") == "pass" else \
           "HALT" if result.get("verdict") == "halt" else "FAIL"
    fb   = "  [FALLBACK]" if result.get("was_fallback") else ""
    exc  = "  [EXCEPTION]" if "exception" in result else ""
    print(f"  {label:<26}: [{icon}]{fb}{exc}")
    print(f"    model_used  : {result.get('model_used', '--')}")
    print(f"    latency_ms  : {_ms(result.get('latency_ms'))}")
    summ = result.get("summary", "")
    if summ:
        print(f"    summary     : {summ[:120]}{'...' if len(summ) > 120 else ''}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print(_SEP2)
    print("  BRIGHTUITY -- Real HTTP End-to-End Pipeline Run")
    print("  5 agent services  |  AGENT_TRANSPORT=http  |  real LLMs  |  no mocks")
    print(_SEP2)

    # -- 1. Start services -----------------------------------------------------
    print("\n  STEP 1 -- Starting agent services")
    print(_SEP)
    procs: list[subprocess.Popen] = []

    try:
        procs = _start_services()
        _wait_for_health(timeout_s=60.0)
        print("  All 5 services healthy.")

        # -- 2. Load client and run pipeline -----------------------------------
        print()
        print(_SEP)
        print("  STEP 2 -- Running pipeline (AGENT_TRANSPORT=http)")
        print(_SEP)

        client = _load_client("REQ-2041")
        print(f"  Client : {client.get('full_name')}  ({client.get('request_id')})")
        print(f"  Asset  : {client.get('asset_type')} -- {client.get('asset_detail')}")
        print(f"  Value  : EUR {client.get('asset_value_eur', 0):,}")
        print(f"  expected_outcome field excluded from all agents (training label only)")
        print()
        print("  Setting AGENT_TRANSPORT=http and calling run_pipeline()...")
        print("  Agent logs stream below:")
        print()

        # Import AFTER dotenv and services are up
        os.environ["AGENT_TRANSPORT"] = "http"
        from agents.orchestrator.orchestrator import run_pipeline

        wall_t0 = time.monotonic()
        decision, events = run_pipeline(client)
        full_wall_ms = int((time.monotonic() - wall_t0) * 1000)

        # -- 3. Print results --------------------------------------------------
        print()
        print(_SEP2)
        print("  PIPELINE RESULTS")
        print(_SEP2)

        agents_d = decision.get("agents", {})
        seal     = decision.get("seal") or {}
        briefing = decision.get("briefing") or {}
        token    = decision.get("token_structure")

        # Stage 1 agents
        print()
        print(_SEP)
        print("  STAGE 1 -- parallel agents (4 concurrent HTTP calls)")
        print(_SEP)
        for name in ("doc_auditor", "kyc_guardian", "dynamic_compliance", "stress_test"):
            _print_agent(name, agents_d.get(name))

        s1_ms     = decision.get("stage1_wall_ms", 0)
        latencies = [
            agents_d.get(a, {}).get("latency_ms", 0)
            for a in ("doc_auditor", "kyc_guardian", "dynamic_compliance", "stress_test")
            if agents_d.get(a)
        ]
        serial_est = sum(latencies)
        speedup    = serial_est / s1_ms if s1_ms else 0
        print()
        print(f"  stage1_wall_ms (HTTP parallel)  : {_ms(s1_ms)}")
        print(f"  sum of agent latencies (serial) : {_ms(serial_est)}")
        print(f"  effective speedup               : {speedup:.1f}x")

        # Gate
        print()
        print(_SEP)
        print("  GOVERNANCE GATE")
        print(_SEP)
        print(f"  gate_outcome : {decision.get('gate_outcome', '--')}")
        print(f"  gate_reason  : {decision.get('gate_reason', '--')[:120]}")

        # Stage 2: tokenizer
        print()
        print(_SEP)
        print("  STAGE 2 -- Asset Tokenizer (HTTP)")
        print(_SEP)
        if token:
            _print_agent("asset_tokenizer", token)
            total_t = token.get("total_tokens", 0)
            per_t   = token.get("value_per_token_eur", 0.0)
            implied = total_t * per_t
            asset_v = client.get("asset_value_eur", 0)
            pct     = abs(implied - asset_v) / asset_v * 100 if asset_v else 0
            print(f"    standard    : {token.get('token_standard', '--')}")
            print(f"    structure   : {total_t:,} tokens x EUR {per_t:,.2f} = EUR {implied:,.0f}"
                  f"  ({pct:+.1f}% vs EUR {asset_v:,})")
        else:
            print("  (skipped -- gate did not pass)")

        # Stage 3: seal
        print()
        print(_SEP)
        print("  STAGE 3 -- ECDSA Seal (ConsensusSigner, always in-process)")
        print(_SEP)
        print(f"  status         : {seal.get('status', '--')}")
        if seal.get("status") == "sealed":
            print(f"  canonical_hash : {seal.get('canonical_hash', '--')}")
            print(f"  sealed_at      : {seal.get('sealed_at', '--')}")
            print(f"  curve          : {seal.get('curve', '--')}")
            gates = seal.get("gates_cleared", [])
            print(f"  gates_cleared  : {', '.join(gates)} ({len(gates)}/5)")
            sig = seal.get("signature", "")
            print(f"  signature      : {sig[:40]}... ({len(sig)//2} bytes)")
        elif seal.get("status") == "blocked":
            print(f"  failed_gate    : {seal.get('failed_gate', '--')}")
            print(f"  reason         : {str(seal.get('reason', '--'))[:120]}")

        # Layer 2 briefing
        print()
        print(_SEP)
        print("  LAYER 2 BRIEFING (Opus 4.8 synthesis)")
        print(_SEP)
        print(f"  source         : {briefing.get('source', '--')}")
        print(f"  model_used     : {briefing.get('model_used', '--')}")
        print(f"  was_fallback   : {briefing.get('was_fallback', '--')}")
        print(f"  latency_ms     : {_ms(briefing.get('latency_ms'))}")
        print()
        print(f"  HEADLINE:")
        print(f"    {briefing.get('headline', '--')}")
        print()
        print(f"  DECISIVE FACTOR:")
        print(f"    {briefing.get('decisive_factor', '--')}")
        print()
        print("  PER-AGENT SUMMARY:")
        for line in briefing.get("per_agent_summary", []):
            print(f"    - {line}")
        print()
        print(f"  RECOMMENDATION:")
        rec = briefing.get("recommendation", "")
        # Wrap at 80 chars
        import textwrap
        for ln in textwrap.wrap(rec, width=70, initial_indent="    ", subsequent_indent="    "):
            print(ln)

        # End-to-end metrics
        print()
        print(_SEP2)
        print("  END-TO-END METRICS (HTTP transport)")
        print(_SEP2)
        print(f"  pipeline_status          : {decision.get('pipeline_status', '--')}")
        print(f"  gate_outcome             : {decision.get('gate_outcome', '--')}")
        print(f"  seal_status              : {seal.get('status', '--')}")
        print(f"  briefing_source          : {briefing.get('source', '--')}")
        print()
        print(f"  stage1_wall_ms (HTTP)    : {_ms(s1_ms)}")
        print(f"  stage1_speedup           : {speedup:.1f}x  (vs serial {_ms(serial_est)})")
        print(f"  layer1_total_ms (L1)     : {_ms(decision.get('total_wall_ms'))}")
        print(f"  synthesis_latency_ms (L2): {_ms(briefing.get('latency_ms'))}")
        print(f"  full_wall_ms (L1+L2)     : {_ms(full_wall_ms)}")

        # Coherence checks
        print()
        status = decision.get("pipeline_status")
        gate   = decision.get("gate_outcome")
        seal_s = seal.get("status")

        checks = [
            ("pipeline_status is valid",
             status in ("approved_pending_human", "halted_kyc", "blocked_gate", "error")),
            ("seal is coherent with gate outcome",
             (gate == "pass") == (seal_s == "sealed")),
            ("briefing was produced",
             bool(briefing.get("headline"))),
            ("pipeline_status = approved_pending_human",
             status == "approved_pending_human"),
            ("seal = sealed",
             seal_s == "sealed"),
        ]
        for label, ok in checks:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}]  {label}")

        print()
        print(_SEP2)
        print("  HTTP end-to-end run complete.")
        print(_SEP2)
        print()

    finally:
        if procs:
            _stop_services(procs)
        # Restore transport env
        os.environ.pop("AGENT_TRANSPORT", None)


if __name__ == "__main__":
    main()
