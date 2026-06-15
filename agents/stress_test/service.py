"""
agents/stress_test/service.py
Brightuity — HTTP service wrapper for the Stress-Test Simulator agent.

Thin FastAPI layer. Accepts the scoped client_record JSON, calls the existing
run_stress_test() function, and returns its verdict dict as JSON.
No business logic here — all logic lives in logic.py unchanged.

Endpoints:
    GET  /health  -> {"status": "ok", "agent": "stress_test"}
    POST /run     -> verdict dict (same shape as run_stress_test() return value)

Start (development):
    uvicorn agents.stress_test.service:app --host 0.0.0.0 --port 8004

Start (module):
    python -m agents.stress_test.service
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Body

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.stress_test.logic import run_stress_test  # noqa: E402

AGENT_NAME = "stress_test"
DEFAULT_PORT = 8004

app = FastAPI(title=f"Brightuity — {AGENT_NAME}", version="1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/run")
def run(client_record: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return run_stress_test(client_record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
