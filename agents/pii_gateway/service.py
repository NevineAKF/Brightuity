"""
agents/pii_gateway/service.py
Brightuity — PII Data-Access Gateway.

Exposes ONLY per-agent whitelisted fields from the Zone 1 PII store.
Raw client records never leave this service — every /scope response contains
exactly AGENT_SCOPES[agent_name] fields (and no others).

Location rationale: mirrors agents/consensus_signer/ — both are standalone
services consumed by the Band agent layer, not by the HTTP backend.  Placing
this in backend/ would invert the dependency graph (agents → backend).
The gateway depends on backend.pii_store (data read) and shared.pii_scopes
(whitelist); nothing in backend/ depends on this service.

Endpoints:
    GET /health
        → {"status": "ok", "service": "pii_gateway",
           "clients_loaded": N, "agents_served": [...]}

    GET /scope/{agent_name}/{request_id}
        → dict containing ONLY AGENT_SCOPES[agent_name] fields for that client.
        400  if agent_name not in AGENT_SCOPES.
        404  if request_id not found.
        Raw un-scoped PII is NEVER returned.

Data source: backend.pii_store.load_clients() — inherits PII_DB_DSN switch
(JSON seed file when unset; PostgreSQL when set).

Environment:
    PII_DB_DSN   — passed through to pii_store (optional).
    PII_GW_PORT  — bind port (default: 8701).

Start (docker-compose):
    python -m agents.pii_gateway.service
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from shared.pii_scopes import AGENT_SCOPES
from backend.pii_store import load_clients

_CLIENTS: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _CLIENTS
    _CLIENTS = load_clients()
    yield


app = FastAPI(
    title="Brightuity PII Gateway",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "pii_gateway",
        "clients_loaded": len(_CLIENTS),
        "agents_served": sorted(AGENT_SCOPES.keys()),
    }


@app.get("/scope/{agent_name}/{request_id}")
def scope(agent_name: str, request_id: str) -> dict[str, Any]:
    """
    Return ONLY the whitelisted fields for agent_name.
    Raw PII beyond the agent's scope is stripped before the response is sent.
    """
    if agent_name not in AGENT_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown agent {agent_name!r}. "
                f"Valid agents: {sorted(AGENT_SCOPES.keys())}"
            ),
        )
    client = _CLIENTS.get(request_id)
    if client is None:
        raise HTTPException(
            status_code=404,
            detail=f"Client {request_id!r} not found.",
        )
    allowed = AGENT_SCOPES[agent_name]
    return {k: client[k] for k in allowed if k in client}


if __name__ == "__main__":
    port = int(os.getenv("PII_GW_PORT", "8701"))
    uvicorn.run(
        "agents.pii_gateway.service:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
