"""
band_agents/run_compliance_agent.py
Brightuity — Dynamic Compliance Band agent entry point (Phase 2b).

Usage:
    python -m band_agents.run_compliance_agent

Reads credentials from .env (gitignored):
    BAND_COMPLIANCE_AGENT_ID  — UUID of the Dynamic Compliance agent on Band
    BAND_COMPLIANCE_API_KEY   — API key for the agent
    THENVOI_WS_URL            — WebSocket URL  (default: wss://app.band.ai/api/v1/socket/websocket)
    THENVOI_REST_URL          — REST base URL  (default: https://app.band.ai)

Once running, @-mention the agent in a Band room with a request_id:
    @DynamicCompliance REQ-2041
    @DynamicCompliance REQ-2043

The agent retrieves relevant regulatory provisions (RAG), runs Gemini 2.5 Pro,
posts a human-readable compliance verdict, then fires a tool_result event with
structured metadata (agent, request_id, verdict, jurisdiction, citations, model_used, latency_ms).

Press Ctrl-C to stop. Graceful shutdown waits up to 30 s for in-flight requests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Load .env before importing anything that reads env vars.
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from band import Agent
from band_agents.compliance_adapter import ComplianceAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _build_agent() -> Agent:
    agent_id = os.environ.get("BAND_COMPLIANCE_AGENT_ID", "")
    api_key  = os.environ.get("BAND_COMPLIANCE_API_KEY", "")
    ws_url   = os.environ.get("THENVOI_WS_URL",  "wss://app.band.ai/api/v1/socket/websocket")
    rest_url = os.environ.get("THENVOI_REST_URL", "https://app.band.ai")

    if not agent_id or not api_key:
        raise RuntimeError(
            "Missing credentials. Set BAND_COMPLIANCE_AGENT_ID and "
            "BAND_COMPLIANCE_API_KEY in .env"
        )

    return Agent.create(
        adapter=ComplianceAdapter(),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )


async def main() -> None:
    agent = _build_agent()
    logger.info(
        "Starting Dynamic Compliance agent (band-sdk %s)",
        __import__("band").__version__,
    )
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
