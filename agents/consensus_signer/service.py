"""
agents/consensus_signer/service.py
Brightuity — Consensus Signer HTTP microservice.

Thin FastAPI wrapper around the EXISTING ConsensusSigner from logic.py.
The cryptographic code is UNCHANGED — this file adds only an HTTP boundary
so the signer can run as an isolated, no-egress container.

Endpoints:
    GET  /health  → {"status": "ok", "agent": "consensus_signer"}
    POST /seal    → SealedProof or BlockedResult (identical JSON shape to the
                    in-process seal_decision() call in agents/orchestrator/core.py)

Start (development):
    uvicorn agents.consensus_signer.service:app --host 0.0.0.0 --port 8700

Start (module — preferred for docker-compose):
    python -m agents.consensus_signer.service

Environment:
    SIGNER_PORT   Port to bind (default: 8700). Only used when run as __main__.
"""
from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from agents.consensus_signer.logic import ConsensusSigner

app = FastAPI(title="Brightuity Consensus Signer", version="1.0.0")

# One ConsensusSigner instance per process — identical semantics to the in-process
# call in agents/orchestrator/core.py.  The key is ephemeral (demo; see the HSM
# notice in logic.py for production requirements).
_signer = ConsensusSigner()


class SealRequest(BaseModel):
    case_record: dict[str, Any]
    agent_verdicts: dict[str, dict[str, Any]]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "consensus_signer"}


@app.post("/seal")
def seal(req: SealRequest) -> dict[str, Any]:
    return _signer.seal(req.case_record, req.agent_verdicts)


if __name__ == "__main__":
    port = int(os.getenv("SIGNER_PORT", "8700"))
    uvicorn.run(
        "agents.consensus_signer.service:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
