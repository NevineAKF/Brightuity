"""
agents/doc_auditor/service.py
Brightuity — HTTP service wrapper for the Doc Auditor agent.

Thin FastAPI layer. Accepts the scoped client_record JSON, calls the existing
audit_documents() function, and returns its verdict dict as JSON.
No business logic here — all logic lives in logic.py unchanged.

Endpoints:
    GET  /health  -> {"status": "ok", "agent": "doc_auditor"}
    POST /run     -> verdict dict (same shape as audit_documents() return value)

Start (development):
    uvicorn agents.doc_auditor.service:app --host 0.0.0.0 --port 8001

Start (module):
    python -m agents.doc_auditor.service
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Body

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.doc_auditor.logic import audit_documents  # noqa: E402

AGENT_NAME = "doc_auditor"
DEFAULT_PORT = 8001

app = FastAPI(title=f"Brightuity — {AGENT_NAME}", version="1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/run")
def run(client_record: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return audit_documents(client_record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
