# Brightuity — AI agents. One human decision. Complete auditability.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](#)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](#)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](#)
[![Band](https://img.shields.io/badge/Coordination-Band%20AI-7C3AED.svg)](#)

> Issuing a token takes minutes. Proving the asset is legitimate takes weeks.
> The bottleneck is not the blockchain — it is the coordination of compliance.

Brightuity is an enterprise B2B vendor system for the **Digital Assets & Tokenization Division** of banks and financial institutions. It replaces weeks of fragmented specialist handoffs with a coordinated pipeline of AI agents that runs in minutes. Every agent verdict, every gate decision, and every coordination message passes through Band — making the coordination room itself the immutable audit trail. Final approval always stays with a human: the Head of Digital Assets.

**Built for the Band of Agents Hackathon** (lablab.ai, June 2026, Track 3: Regulated & High-Stakes Workflows).

**Live demo:** http://brightuity.duckdns.org/login

---

## 🏗 Architecture

### Agent Roster

Eight components run the pipeline. Five call LLMs. Two are pure deterministic Python. One is ECDSA cryptography. All coordination flows through Band.

| # | Agent | Role | Primary model | Fallback | Platform |
|---|---|---|---|---|---|
| 1 | **Orchestrator** | Deterministic pipeline coordinator; parallel Stage 1 dispatch; governance gate enforcement; post-gate LLM briefing synthesis | `claude-opus-4-8` *(synthesis only)* | `claude-sonnet-4-6` | AI/ML API |
| 2 | **Doc Auditor** | Document completeness, ownership chain, valuation support | `google/gemini-3-5-flash` | `gpt-4o` | AI/ML API |
| 3 | **KYC Guardian** | Identity, sanctions screening, PEP detection, source-of-funds | `claude-opus-4-8` | `gpt-4o` | AI/ML API |
| 4 | **Dynamic Compliance** | RAG-grounded multi-jurisdiction regulatory opinion (MiCA, AMLD5) | `google/gemini-2.5-pro` | `gpt-4o` | AI/ML API |
| 5 | **Stress-Test Simulator** | Fair value, risk score 0–100, scenario stress testing | `google/gemini-3-5-flash` | `gpt-4o` | AI/ML API |
| 6 | **Asset Tokenizer** | ERC-3643 token structure: supply, unit price, transfer rules | `gpt-4o` | `google/gemini-2.5-pro` | AI/ML API |
| 7 | **Consensus Signer** | ECDSA seal — verifies all five gates passed, hashes and signs the canonical record | *No LLM* | — | Local (Python `cryptography`) |
| 8 | **Governance & Audit** | Assembles all verdicts, proofs, and audit trail into the Decision Evidence Package | *No LLM* | — | Local (deterministic Python) |

> **Note on the Orchestrator:** The coordination logic — dispatching agents, enforcing the governance gate, deciding pipeline status — is pure deterministic Python using `ThreadPoolExecutor`. The Orchestrator makes no LLM calls for decisions. It calls an LLM exactly once, after the gate has already sealed, to generate a human-readable briefing summary. This is a deliberate architectural choice: the audit trail must be reproducible, and gate decisions must be identical every run.

### Pipeline Flow

```
 Browser ──:80──► nginx (SPA + /api proxy)
                       │
                       ▼
              FastAPI backend ──POST /run──► triggers Band room
                       │
                       │ polls Band /context for result
                       │
                       ▼
          ┌────────────────────────────────────────────────────────┐
          │                 Band Room (app.band.ai)                │
          │                                                        │
          │  Orchestrator @mentions each Stage 1 agent separately: │
          │                                                        │
          │   ┌──────────────┐  ┌─────────────┐                  │
          │   │  Doc Auditor │  │ KYC Guardian│  ← parallel       │
          │   └──────┬───────┘  └──────┬──────┘                  │
          │   ┌──────┴───────┐  ┌──────┴──────┐                  │
          │   │   Compliance │  │ Stress-Test │                  │
          │   └──────┬───────┘  └──────┬──────┘                  │
          │          └─────────┬────────┘                         │
          │              all verdicts collected                    │
          │                    │                                   │
          │          Governance Gate (deterministic Python)        │
          │                    │                                   │
          │         PASS ──────┤──── HALT/BLOCKED                 │
          │           │        │         │                         │
          │           ▼        │    stop, no seal issued           │
          │    Asset Tokenizer │                                   │
          │           │        │                                   │
          │           ▼        │                                   │
          │    Consensus Signer (in-process ECDSA)                │
          │    ── SealedProof "DGP-XXXX" if all 5 PASS ──        │
          │    ── BlockedResult otherwise ──                       │
          │                                                        │
          │    result re-posted to room → backend receives it      │
          └────────────────────────────────────────────────────────┘
                       │
                       ▼
           Governance & Audit assembles Evidence Package
                       │
                       ▼
           Human Authorization (Approve / Reject + e-signature)
```

---

## 🛡 How Band Coordinates the Agents

Each case gets its own Band room. The backend posts a trigger message @mentioning the Orchestrator with the `request_id`. The Orchestrator posts four separate @mention messages — one per Stage 1 agent — and a background task monitors their replies. Agents that have acknowledged but not yet responded are never re-mentioned; only genuinely silent agents receive bounded nudges (max 3 retries over 90 seconds, absolute 180-second ceiling).

Every agent posts its verdict as a Band message. The Orchestrator parses verdicts from message content, not from a shared database. The Band room is the coordination protocol and the audit trail simultaneously: timestamped, immutable, replayable by anyone with room access.

---

## 🔒 Security Model

### Four Docker Network Zones

| Zone | Network | Members | Internet route |
|---|---|---|---|
| 1 — PII | `zone_pii` (`internal: true`) | `db1_pii`, `pii_seed`, `pii_gateway`, `backend` | None |
| 2 — Agents | `zone_agents` (`internal: true`) | Band agent containers, `pii_gateway`, `egress_proxy` | Via Squid allow-list only |
| 3 — Coord | `zone_coord` (`internal: true`) | `consensus_signer`, `orchestrator` | None |
| Edge | `edge` | `egress_proxy`, `backend` (:8000), `frontend` (:80) | Restricted |

`db1_pii` (Zone 1, `internal: true`) has no internet routing path by construction. Band coordination traffic carries only `request_id` and verdict text — never raw PII or documents. The PII Gateway enforces per-agent field scoping: each agent receives only the fields in its declared `frozenset` whitelist.

### Egress Allow-List (Squid, `infra/egress_proxy/squid.conf`)

```
api.aimlapi.com     — all LLM agent calls
api.featherless.ai  — reserved / legacy (currently no active agent calls)
app.band.ai         — Band SDK WebSocket (wss://) + REST
```

All other outbound connections are refused and dropped. WebSocket connections use Squid's HTTP CONNECT tunneling.

### Dual-Layer Gate System

**Layer 1 (Orchestrator, Python):** KYC `halt` is an absolute veto — pipeline stops immediately, tokenizer never runs. A non-passing verdict from Doc Auditor, Compliance, or KYC (non-halt) blocks the tokenizer. Stress-Test is advisory at Layer 1 — the tokenizer still runs so the human sees the proposed structure alongside the risk report.

**Layer 2 (Consensus Signer, ECDSA):** All five gates must return `pass` before a seal is produced. A Stress-Test `fail` that passed Layer 1 is caught here: tokenizer ran, human sees the structure, but no seal is issued. Status: `blocked_gate`.

The Consensus Signer seals **integrity, not correctness.** It guarantees the recorded verdict set was not altered after sealing. Whether the verdicts reflect accurate analysis is the responsibility of each agent's anti-hallucination design and the human reviewer's judgment.

---

## ⚙️ Tech Stack

| Layer | Technology | Source |
|---|---|---|
| Frontend | React + Vite + Three.js (3D token) + react-router-dom | `frontend/` |
| Reverse proxy | nginx 1.27-alpine — SPA routing + `/api/` proxy | `frontend/nginx.conf` |
| Backend | FastAPI 0.115 + Uvicorn, Python 3.11 | `requirements.txt` |
| PII database | PostgreSQL 16 (`db1_pii`, zone isolated) | `docker-compose.yml` |
| Case store | SQLite via `backend/case_store.py` | `backend/case_store.py` |
| Agent coordination | `band-sdk==1.0.0` + `thenvoi-client-rest==0.0.7` | `requirements.txt` |
| LLM client | `openai==2.41.1` — OpenAI-compatible client used for all providers | `requirements.txt` |
| LLM provider | AI/ML API (`api.aimlapi.com`) — all five LLM agents | `shared/config.py` |
| RAG | `chromadb==1.5.9` + `sentence-transformers==5.5.1` (embedding: `all-MiniLM-L6-v2`, baked into image) | `requirements.txt`, `Dockerfile:48` |
| RAG corpus | MiCA + AMLD5 provisions (`rag_corpus/sources/`) indexed into ChromaDB | `rag_corpus/build_index.py` |
| Cryptography | Python `cryptography==49.0.0` — ECDSA seal + Layer-2 authorization signature | `requirements.txt` |
| Egress control | Squid — HTTP CONNECT proxy, 3-entry allow-list | `infra/egress_proxy/squid.conf` |
| Containerization | Docker Compose — one container per agent, four isolated networks | `docker-compose.yml` |

---

## 📁 Repository Structure

```
Brightuity/
├── frontend/                 React + Vite SPA; Dockerfile.web, nginx.conf
├── backend/                  FastAPI gateway (main.py), band_bridge, case_store,
│                             authorization_signer, pdf_renderer, pii_store
├── agents/                   Agent logic (one subdirectory per agent):
│   ├── orchestrator/         Deterministic pipeline + LLM synthesis
│   ├── doc_auditor/          Document verification (Gemini 3.5 Flash)
│   ├── kyc_guardian/         KYC/AML screening (Claude Opus 4.8)
│   ├── dynamic_compliance/   RAG-grounded compliance (Gemini 2.5 Pro)
│   ├── stress_test/          Risk + scenario modelling (Gemini 3.5 Flash)
│   ├── asset_tokenizer/      Token structure design (GPT-4o)
│   ├── consensus_signer/     ECDSA seal — no LLM
│   ├── governance_audit/     Evidence package assembly — no LLM
│   └── pii_gateway/          Field-scoped PII service (Zone 1 bridge)
├── band_agents/              Band SDK adapters — run_*.py + *_adapter.py
│                             (one per agent; real Band WebSocket connections)
├── shared/                   call_agent_model.py (failover engine), config.py
│                             (model chains), schemas.py
├── database/                 brightuity_clients.json (100 synthetic clients),
│                             seed_pii_db.py
├── rag_corpus/               MiCA + AMLD5 source JSON, build_index.py,
│                             chroma_index/ (built at Docker image build time)
├── infra/egress_proxy/       Dockerfile + squid.conf (egress allow-list)
├── docs/                     Architecture and agent specification stubs
├── docker-compose.yml        Full multi-service compose with zone isolation
├── Dockerfile                Shared Python 3.11 image (bakes embedding model)
└── .env.example              All required environment variables — copy to .env
```

---

## 🚀 Run Locally

### Prerequisites

- Docker + Docker Compose v2
- Band AI credentials — one `(agent_id, api_key)` pair per Band agent ([app.band.ai](https://app.band.ai))
- AI/ML API key ([api.aimlapi.com](https://api.aimlapi.com))

### 1. Configure environment

```bash
cp .env.example .env
# Fill in all values — see .env.example for full documentation:
#   AIMLAPI_KEY
#   BAND_BACKEND_API_KEY / BAND_BACKEND_AGENT_ID
#   BAND_ORCHESTRATOR_API_KEY / BAND_ORCHESTRATOR_AGENT_ID
#   BAND_KYC_API_KEY / BAND_KYC_AGENT_ID
#   BAND_COMPLIANCE_API_KEY / BAND_COMPLIANCE_AGENT_ID
#   BAND_DOCAUDITOR_API_KEY / BAND_DOCAUDITOR_AGENT_ID
#   BAND_STRESSTEST_API_KEY / BAND_STRESSTEST_AGENT_ID
#   BAND_TOKENIZER_API_KEY / BAND_TOKENIZER_AGENT_ID
#   BAND_CONSENSUS_AGENT_ID / BAND_GOVERNANCE_AGENT_ID
#   POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / PII_DB_DSN
#   JWT_SECRET  (generate: python -c "import secrets; print(secrets.token_hex(32))")
```

### 2. Build and run

```bash
docker compose build   # builds shared Python image (bakes all-MiniLM-L6-v2 + RAG index)
docker compose up      # starts all 13 services in dependency order
```

| Service | URL |
|---|---|
| Frontend (React SPA) | http://localhost |
| Backend API | http://localhost:8000 |
| API health | http://localhost:8000/health |
| API docs | http://localhost:8000/docs |

### 3. Trigger a case

Via the frontend: log in → select a pending case → **Start Processing**.

Via the API directly:

```bash
# Trigger pipeline (returns 202 immediately; pipeline runs ~60–90 s)
curl -X POST http://localhost:8000/cases/REQ-2041/run

# Poll for completion
curl http://localhost:8000/cases/REQ-2041/status

# Retrieve Decision Evidence Package
curl http://localhost:8000/cases/REQ-2041/package
```

---

## ✅ Demonstrated Outcomes

Two cases prove both decision paths. Outcomes emerge from the 100-client synthetic dataset — nothing is hardcoded.

**Marcus Weber · REQ-2041 · Commercial Real Estate (DE) · €2.50M → APPROVE**
All five gates cleared. Consensus Signer issued seal `DGP-7F3A-2041`. Asset Tokenizer proposed 2,500 ERC-3643 tokens at €1,000 each with KYC-gated transfers. Human authorized. Full approve path confirmed end-to-end.

**Viktor Petrov · REQ-2043 · PEP Flag → HALT (no seal)**
KYC Guardian detected a PEP match. Hard `halt` verdict triggered Layer 1 veto — pipeline stopped before the Asset Tokenizer ran. Consensus Signer was never invoked; no seal was issued. Proves the governance gate is unconditional.

---

## 📜 License & Credits

**MIT** — see [LICENSE](LICENSE).

Built by **Nevine Fakhreddin** ([@NevineAKF](https://github.com/NevineAKF)) — solo submission, Band of Agents Hackathon, lablab.ai, June 2026.

---

## Verification Index

Every framework, model, and provider named in this README is verified against a specific file and line:

| Claim | File | Evidence |
|---|---|---|
| Python 3.11 | `Dockerfile:11` | `FROM python:3.11-slim` |
| FastAPI 0.115 | `requirements.txt:18` | `fastapi==0.115.0` |
| band-sdk 1.0.0 | `requirements.txt:10` | `band-sdk==1.0.0` |
| thenvoi-client-rest 0.0.7 | `requirements.txt:11` | `thenvoi-client-rest==0.0.7` |
| openai 2.41.1 (LLM client) | `requirements.txt:38` | `openai==2.41.1` |
| chromadb 1.5.9 | `requirements.txt:50` | `chromadb==1.5.9` |
| sentence-transformers 5.5.1 | `requirements.txt:51` | `sentence-transformers==5.5.1` |
| all-MiniLM-L6-v2 embedding | `Dockerfile:51`, `agents/dynamic_compliance/retrieval.py:24` | `SentenceTransformer('all-MiniLM-L6-v2')` |
| cryptography 49.0.0 | `requirements.txt:44` | `cryptography==49.0.0` |
| reportlab (PDF) | `requirements.txt:150` | `reportlab` |
| AI/ML API as sole LLM provider | `shared/config.py:101–205` | All 5 `ModelChain` entries use `Platform.AIMLAPI` |
| claude-opus-4-8 (Orchestrator, KYC) | `shared/config.py:136, 159` | `primary="claude-opus-4-8"` |
| claude-sonnet-4-6 (Orchestrator fallback) | `shared/config.py:137` | `fallback="claude-sonnet-4-6"` |
| google/gemini-3-5-flash (Doc, Stress) | `shared/config.py:148, 182` | `primary="google/gemini-3-5-flash"` |
| google/gemini-2.5-pro (Compliance primary, Tokenizer fallback) | `shared/config.py:170, 200` | `primary="google/gemini-2.5-pro"` / `fallback="google/gemini-2.5-pro"` |
| gpt-4o (KYC/Doc/Compliance/Stress fallback; Tokenizer primary) | `shared/config.py:150, 163, 173, 186, 197` | `fallback="gpt-4o"` / `primary="gpt-4o"` |
| Orchestrator is pure Python (no LLM for coordination) | `agents/orchestrator/orchestrator.py:8–13` | "NOT an LLM agent. Pure deterministic Python control flow." |
| No CrewAI | `agents/orchestrator/orchestrator.py:9` | "Decision to NOT use CrewAI" + absent from `requirements.txt` |
| No LangChain | `requirements.txt` (all 151 lines) | `langchain` does not appear |
| ECDSA seal (Consensus Signer) | `agents/consensus_signer/logic.py:21–28` | SHA-256 + ECDSA described in module docstring |
| Governance & Audit: no LLM | `agents/governance_audit/logic.py:23` | "No LLM calls, no new verdicts, no gate changes." |
| RAG corpus: MiCA + AMLD5 | `rag_corpus/sources/mica_provisions.json`, `rag_corpus/sources/amld_provisions.json` | Files present |
| Squid allow-list (3 entries) | `infra/egress_proxy/squid.conf:19–21` | `acl brightuity_allowed dstdomain` ×3 |
| zone_pii internal:true | `docker-compose.yml:347–349` | `zone_pii: driver: bridge / internal: true` |
| zone_agents internal:true | `docker-compose.yml:351–353` | `zone_agents: driver: bridge / internal: true` |
| zone_coord internal:true | `docker-compose.yml:355–357` | `zone_coord: driver: bridge / internal: true` |
| nginx frontend service | `docker-compose.yml:341–352`, `frontend/nginx.conf` | `frontend:` service, `location /api/` proxy block |
