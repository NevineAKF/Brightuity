"""
band_agents/run_kyc_agent.py
Brightuity — KYC Guardian Band agent entry point (Phase 2a spike).

Usage:
    python -m band_agents.run_kyc_agent

Reads credentials from .env (gitignored):
    BAND_KYC_AGENT_ID   — UUID of the KYC Guardian agent on Band
    BAND_KYC_API_KEY    — API key for the agent
    THENVOI_WS_URL      — WebSocket URL  (default: wss://app.band.ai/api/v1/socket/websocket)
    THENVOI_REST_URL    — REST base URL  (default: https://app.band.ai)

Once running, @-mention the agent in a Band room with a request_id:
    @KycGuardian REQ-2041
    @KycGuardian run REQ-2043

The agent replies with a structured verdict + fires a tool_result event with
metadata (agent, request_id, verdict, match_type, match_score, model_used, latency_ms).

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
from band_agents.kyc_adapter import KycAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _build_agent() -> Agent:
    agent_id = os.environ.get("BAND_KYC_AGENT_ID", "")
    api_key  = os.environ.get("BAND_KYC_API_KEY", "")
    ws_url   = os.environ.get("THENVOI_WS_URL",  "wss://app.band.ai/api/v1/socket/websocket")
    rest_url = os.environ.get("THENVOI_REST_URL", "https://app.band.ai")

    if not agent_id or not api_key:
        raise RuntimeError(
            "Missing credentials. Set BAND_KYC_AGENT_ID and BAND_KYC_API_KEY in .env"
        )

    return Agent.create(
        adapter=KycAdapter(),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )


async def main() -> None:
    agent = _build_agent()
    logger.info("Starting KYC Guardian agent (band-sdk %s)", __import__("band").__version__)
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
