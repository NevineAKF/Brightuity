"""
band_agents/run_stresstest_agent.py
Brightuity — Stress-Test Simulator Band agent entry point (Phase 2d).

Usage:
    python -m band_agents.run_stresstest_agent

Reads credentials from .env (gitignored):
    BAND_STRESSTEST_AGENT_ID  — UUID of the Stress-Test agent on Band
    BAND_STRESSTEST_API_KEY   — API key for the agent
    THENVOI_WS_URL            — WebSocket URL  (default: wss://app.band.ai/api/v1/socket/websocket)
    THENVOI_REST_URL          — REST base URL  (default: https://app.band.ai)

Once running, @-mention the agent in a Band room with a request_id:
    @StressTest REQ-2041
    @StressTest REQ-2043

The agent runs the deterministic risk engine first (risk_score, risk_band,
verdict), then calls DeepSeek-V4-Pro for the interpretive narrative, posts the
full result, and fires a tool_result event with structured metadata.

Press Ctrl-C to stop. Graceful shutdown waits up to 30 s for in-flight requests.
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
from band_agents.stresstest_adapter import StressTestAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _build_agent() -> Agent:
    agent_id = os.environ.get("BAND_STRESSTEST_AGENT_ID", "")
    api_key  = os.environ.get("BAND_STRESSTEST_API_KEY", "")
    ws_url   = os.environ.get("THENVOI_WS_URL",  "wss://app.band.ai/api/v1/socket/websocket")
    rest_url = os.environ.get("THENVOI_REST_URL", "https://app.band.ai")

    if not agent_id or not api_key:
        raise RuntimeError(
            "Missing credentials. Set BAND_STRESSTEST_AGENT_ID and "
            "BAND_STRESSTEST_API_KEY in .env"
        )

    return Agent.create(
        adapter=StressTestAdapter(),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )


async def main() -> None:
    agent = _build_agent()
    logger.info(
        "Starting Stress-Test Simulator agent (band-sdk %s)",
        __import__("band").__version__,
    )
    await agent.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
