"""
agents/asset_tokenizer/service.py
Brightuity — HTTP service wrapper for the Asset Tokenizer agent.

Thin FastAPI layer. Accepts the scoped client_record JSON, calls the existing
design_token_structure() function, and returns its verdict dict as JSON.
No business logic here — all logic lives in logic.py unchanged.

Endpoints:
    GET  /health  -> {"status": "ok", "agent": "asset_tokenizer"}
    POST /run     -> verdict dict (same shape as design_token_structure() return value)

Start (development):
    uvicorn agents.asset_tokenizer.service:app --host 0.0.0.0 --port 8005

Start (module):
    python -m agents.asset_tokenizer.service
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Body

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.asset_tokenizer.logic import design_token_structure  # noqa: E402

AGENT_NAME = "asset_tokenizer"
DEFAULT_PORT = 8005

app = FastAPI(title=f"Brightuity — {AGENT_NAME}", version="1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/run")
def run(client_record: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return design_token_structure(client_record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
