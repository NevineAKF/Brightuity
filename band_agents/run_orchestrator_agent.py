"""
band_agents/run_orchestrator_agent.py
Brightuity — Orchestrator Band agent entry point (Phase 2g).

Usage:
    python -m band_agents.run_orchestrator_agent

Reads credentials from .env (gitignored):
    BAND_ORCHESTRATOR_AGENT_ID  — UUID of the Orchestrator agent on Band
    BAND_ORCHESTRATOR_API_KEY   — API key for the agent
    THENVOI_WS_URL              — WebSocket URL  (default: wss://app.band.ai/api/v1/socket/websocket)
    THENVOI_REST_URL            — REST base URL  (default: https://app.band.ai)

Once running, @-mention the agent in a Band room with a request_id:
    @Orchestrator REQ-2041
    @Orchestrator REQ-2043

The agent runs the full Brightuity compliance pipeline in-process:
  Stage 1 (parallel): Doc Auditor, KYC Guardian, Dynamic Compliance,
                      Stress-Test Simulator
  Gate check:         deterministic _evaluate_governance_gate
  Stage 2:            Asset Tokenizer (if gate passes)
  Stage 3:            ConsensusSigner.seal() → SealedProof or BlockedResult

Pipeline outcomes:
  approved_pending_human — all 5 gates passed, ECDSA seal produced
  halted_kyc             — KYC Guardian issued halt (absolute veto)
  blocked_gate           — mandatory gate failed, or stress_test fail at seal

No other Band agents need to be running. The orchestrator is self-contained.

Press Ctrl-C to stop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from band import Agent
from band_agents.orchestrator_adapter import OrchestratorAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _build_agent() -> Agent:
    agent_id = os.environ.get("BAND_ORCHESTRATOR_AGENT_ID", "")
    api_key  = os.environ.get("BAND_ORCHESTRATOR_API_KEY", "")
    ws_url   = os.environ.get("THENVOI_WS_URL",  "wss://app.band.ai/api/v1/socket/websocket")
    rest_url = os.environ.get("THENVOI_REST_URL", "https://app.band.ai")

    if not agent_id or not api_key:
        raise RuntimeError(
            "Missing credentials. Set BAND_ORCHESTRATOR_AGENT_ID and "
            "BAND_ORCHESTRATOR_API_KEY in .env"
        )

    return Agent.create(
        adapter=OrchestratorAdapter(),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )


async def main() -> None:
    agent = _build_agent()
    logger.info(
        "Starting Orchestrator agent (band-sdk %s)",
        __import__("band").__version__,
    )
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
