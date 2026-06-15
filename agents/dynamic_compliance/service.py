"""
agents/dynamic_compliance/service.py
Brightuity — HTTP service wrapper for the Dynamic Compliance agent.

Thin FastAPI layer. Accepts the scoped client_record JSON, calls the existing
assess_compliance() function, and returns its verdict dict as JSON.
No business logic here — all logic lives in logic.py unchanged.

Endpoints:
    GET  /health  -> {"status": "ok", "agent": "dynamic_compliance"}
    POST /run     -> verdict dict (same shape as assess_compliance() return value)

Start (development):
    uvicorn agents.dynamic_compliance.service:app --host 0.0.0.0 --port 8003

Start (module):
    python -m agents.dynamic_compliance.service
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Body

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.dynamic_compliance.logic import assess_compliance  # noqa: E402

AGENT_NAME = "dynamic_compliance"
DEFAULT_PORT = 8003

app = FastAPI(title=f"Brightuity — {AGENT_NAME}", version="1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/run")
def run(client_record: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return assess_compliance(client_record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
