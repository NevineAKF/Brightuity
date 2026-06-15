"""
agents/kyc_guardian/service.py
Brightuity — HTTP service wrapper for the KYC Guardian agent.

Thin FastAPI layer. Accepts the scoped client_record JSON, calls the existing
screen_kyc() function, and returns its verdict dict as JSON.
No business logic here — all logic lives in logic.py unchanged.

Endpoints:
    GET  /health  -> {"status": "ok", "agent": "kyc_guardian"}
    POST /run     -> verdict dict (same shape as screen_kyc() return value)

Start (development):
    uvicorn agents.kyc_guardian.service:app --host 0.0.0.0 --port 8002

Start (module):
    python -m agents.kyc_guardian.service
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Body

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.kyc_guardian.logic import screen_kyc  # noqa: E402

AGENT_NAME = "kyc_guardian"
DEFAULT_PORT = 8002

app = FastAPI(title=f"Brightuity — {AGENT_NAME}", version="1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/run")
def run(client_record: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return screen_kyc(client_record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
