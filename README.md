# Brightuity

> **Seven AI agents. One human decision. Complete auditability.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![Band of Agents Hackathon](https://img.shields.io/badge/Hackathon-Band%20of%20Agents%202026-gold)](#)
[![Coordination](https://img.shields.io/badge/Coordination-Band%20AI-purple)](#)

**Brightuity** is an enterprise B2B vendor system for the **Digital Assets & Tokenization Division** of banks and financial institutions. It automates the compliance and verification pipeline that turns a real-world asset — property, gold, securities — into a tradeable digital token, replacing weeks of fragmented specialist work with a coordinated team of AI agents. Final approval always stays with a human: the Head of Digital Assets. Every decision is signed, sealed, and fully auditable.

Built for the **Band of Agents Hackathon** (lablab.ai, June 2026, Track 3: Regulated & High-Stakes Workflows).

---

## Why It Matters

Issuing a token takes minutes. Proving an asset and its owner are legitimate enough to tokenize takes weeks. The bottleneck is not the blockchain — it is the coordination of compliance. A request queues across a document specialist, KYC officer, compliance lawyer, risk analyst, and structuring engineer, each in a different tool, each re-explaining context, each handoff bleeding time and risk.

The numbers are stark: RWA tokenization surpassed **$25 billion on-chain in early 2026** against a backdrop of **$450 trillion in tokenizable global assets** (McKinsey: $2T by 2030; BCG: $16T). A single KYC review costs $1,500–$3,500; AML enforcement hit **$4.6 billion in fines in 2024** (Docusign); 90% of banks report manual KYC error potential affects risk decisions (Fenergo). Brightuity compresses the multi-week specialist pipeline into a single, auditable, human-authorized decision session.

---

## Key Features

- **Multi-agent coordination via Band** — specialist AI agents collaborate through Band's @mention protocol in a persistent room. The coordination log is the audit trail: timestamped, immutable, replayable.
- **Cross-framework architecture** — Orchestrator (CrewAI), Dynamic Compliance (LangChain + ChromaDB RAG), and four plain-Python agents all coordinate through Band, proving interoperability across agent frameworks.
- **Deterministic governance gate** — no token structure is ever designed, and no seal is ever issued, unless all five mandatory gates (Doc, KYC, Compliance, Risk, Tokenizer) return PASS. Enforced in Python, not in an LLM prompt.
- **Real ECDSA seal** — the Consensus Signer is a pure-Python, no-LLM component. It hashes the canonical decision record and signs it with ECDSA, producing a tamper-evident "Deterministic Gateway Proof."
- **RAG-grounded compliance** — Dynamic Compliance retrieves relevant provisions from a ChromaDB index of real MiCA and AMLD5 regulatory texts before reasoning. It never relies on LLM memory alone.
- **Automatic silent failover** — every LLM agent carries a designated fallback model on a different provider. Failover triggers on timeout, rate limit, or credit exhaustion. Proven live on June 12 2026 when a US export-control directive suspended Claude Fable 5 mid-hackathon; Gemini 3.1 Pro was promoted to primary by changing one line.
- **Controlled-egress zoned security** — four Docker network zones isolate PII data from agent coordination traffic. Outbound internet is restricted to a three-endpoint Squid allow-list. Architected in alignment with ISO 27001 / SOC 2 / DORA principles.
- **Human-in-the-loop authorization** — the system produces a signed recommendation; a licensed human officer must explicitly approve or reject with a mandatory reason and e-signature. The authorization record is cryptographically bound to the decision evidence.

---

## Architecture

### The Eight Components

| # | Component | Role | Model / Engine | Provider |
|---|---|---|---|---|
| 1 | **Orchestrator** | Coordinates the pipeline; @-delegates to agents; enforces governance gate; compiles report | Claude Opus 4.8 → Claude Sonnet 4.6 (fallback) | AI/ML API |
| 2 | **Doc Auditor** | Examines deeds, valuations, registry filings; extracts key fields; flags anomalies | Qwen 3.6 → Gemma-4 (fallback) | Featherless |
| 3 | **KYC Guardian** | Identity verification, sanctions/PEP screening, source-of-funds analysis | Claude Opus 4.8 → GPT (fallback) | AI/ML API |
| 4 | **Dynamic Compliance** | RAG-grounded multi-jurisdiction regulatory opinion (MiCA, AMLD5, local law) | Gemini 3.1 Pro → GPT (fallback) | AI/ML API |
| 5 | **Stress-Test Simulator** | Fair value, risk score 0–100, downturn / rate-shock / liquidity scenario analysis | DeepSeek-V4-Pro → Qwen 3.6 (fallback) | Featherless |
| 6 | **Asset Tokenizer** | Designs token structure: supply, unit price, ERC-3643 class, transfer restrictions, governance | Kimi-K2.6 → GLM 4.6 (fallback) | Featherless |
| 7 | **Consensus Signer** | Verifies all gates cleared; ECDSA-seals the Decision Evidence Package | No LLM — pure Python ECDSA | Local |
| 8 | **Governance & Audit** | Assembles all verdicts, proofs, and audit trail into the final evidence package | No LLM — deterministic assembly | Local |

**Platform split is intentional:** AI/ML API handles the three most sensitive agents (identity, compliance, orchestration); Featherless handles analytical workloads (document inspection, risk modelling, token structuring). Both providers qualify for their respective hackathon partner prizes and together demonstrate a sovereign, source-agnostic model strategy.

### Pipeline Flow

```
Human: "Start Processing" on a pending case
        │
        ▼
Backend (FastAPI) ──creates Band room──▶ Orchestrator
        │
        ▼
┌────────────────────────────────────────────────────────┐
│               Stage 1 — Parallel Verdicts              │
│   Doc Auditor  ·  KYC Guardian  ·  Dynamic Compliance  │
│                ·  Stress-Test Simulator                 │
│   (each @mentioned by Orchestrator via Band;           │
│    verdicts posted back to the coordination room)      │
└───────────────────────┬────────────────────────────────┘
                        │
               All five gates PASS?
              /                      \
            YES                      NO (any HALT or FAIL)
             │                         │
             ▼                         ▼
    Stage 2 — Asset              Pipeline stops.
      Tokenizer                  No seal issued.
             │                   Human notified.
             ▼
    Stage 3 — Consensus Signer
    (ECDSA seal → "DGP-XXXX-XXXX")
             │
             ▼
    Governance & Audit
    (Decision Evidence Package assembled)
             │
             ▼
    Human Authorization
    (Approve / Reject + mandatory reason + e-signature)
```

The Band coordination room is the persistent audit trail. Every @mention, every verdict, every gate result is timestamped and immutable. Judges and auditors can replay the exact decision sequence post-hoc.

---

## Security Model

Brightuity uses a **controlled-egress zoned architecture**. It is explicitly not an air-gap — it connects to Band and AI providers over the internet. Claiming "air-gap" would be technically false; the honest framing is network-isolation-boundary with controlled, allow-listed egress.

### Four Docker Network Zones

| Zone | Docker Network | Contents | Internet path |
|---|---|---|---|
| Zone 1 — PII | `zone_pii` (`internal: true`) | `db1_pii`, `pii_seed`, `pii_gateway`, `backend` | None |
| Zone 2 — Agents | `zone_agents` (`internal: true`) | 6 Band agents, `pii_gateway`, `egress_proxy` | Via Squid only |
| Zone 3 — Coord | `zone_coord` (`internal: true`) | `consensus_signer`, `orchestrator` | None |
| Edge | `edge` | `egress_proxy` (controlled outbound), `backend` (:8000), `frontend` (:80) | Restricted |

`db1_pii` has no internet routing path by construction. Band coordination traffic carries only request IDs, @mentions, and verdicts — never raw PII or documents.

### Egress Allow-List (Squid)

Outbound internet from `zone_agents` passes through a Squid HTTP CONNECT proxy with a three-entry allow-list:

```
api.aimlapi.com       # Orchestrator, KYC Guardian, Dynamic Compliance
api.featherless.ai    # Doc Auditor, Stress-Test Simulator, Asset Tokenizer
app.band.ai           # All Band SDK WebSocket (wss://) + REST connections
```

All other outbound connections are refused at the proxy. WebSocket tunneling uses Squid's HTTP CONNECT mechanism.

### Honest Framing

| Claim | What it means |
|---|---|
| "ISO 27001 / SOC 2 / DORA-aligned, certification-ready" | Implements the control principles. Formal certification is a process, not a code property. |
| "HSM-ready" | ECDSA key lives in a Docker volume (`AUTH_KEY_PATH`). The signing interface is designed for HSM migration. |
| "Cryptographically-bound authorization record" | Layer-2 ECDSA authorization signature provides tamper-evidence and non-repudiation within the system. Not eIDAS-qualified. |
| Synthetic data | 100-client dataset is fully synthetic. No real PII is used anywhere in the codebase or demo. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 5, Three.js (3D token visualization), react-router-dom 6 |
| Reverse proxy | nginx 1.27-alpine — SPA routing + `/api/` proxy to backend |
| Backend | FastAPI (Python 3.12), Uvicorn, SQLite case store |
| PII database | PostgreSQL 16 (Docker `zone_pii`, `internal: true`) |
| RAG | ChromaDB + `sentence-transformers` — MiCA and AMLD5 provisions index |
| Agent coordination | Band AI — WebSocket SDK, @mention protocol, persistent chat rooms |
| Agent frameworks | CrewAI (Orchestrator), LangChain (Dynamic Compliance), plain Python (others) |
| LLM providers | AI/ML API (Orchestrator, KYC, Compliance), Featherless (Doc, Risk, Tokenizer) |
| Cryptography | Python `ecdsa` / `cryptography` — ECDSA seal + Layer-2 authorization signature |
| Egress control | Squid — HTTP CONNECT proxy, 3-endpoint allow-list |
| Containerization | Docker Compose — one container per agent, zone isolation via named networks |
| Hosting | Vultr VPS |

---

## Getting Started

### Prerequisites

- Docker + Docker Compose v2
- Band AI agent credentials — one API key + UUID per agent ([app.band.ai](https://app.band.ai))
- AI/ML API key ([api.aimlapi.com](https://api.aimlapi.com))
- Featherless API key ([featherless.ai](https://featherless.ai))

### 1. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in every value. Required keys:

```
# AI providers
AIMLAPI_KEY
FEATHERLESS_KEY

# Band — one key + UUID per agent
BAND_BACKEND_API_KEY      BAND_BACKEND_AGENT_ID
BAND_ORCHESTRATOR_API_KEY BAND_ORCHESTRATOR_AGENT_ID
BAND_KYC_API_KEY          BAND_KYC_AGENT_ID
BAND_COMPLIANCE_API_KEY   BAND_COMPLIANCE_AGENT_ID
BAND_DOCAUDITOR_API_KEY   BAND_DOCAUDITOR_AGENT_ID
BAND_STRESSTEST_API_KEY   BAND_STRESSTEST_AGENT_ID
BAND_TOKENIZER_API_KEY    BAND_TOKENIZER_AGENT_ID
BAND_CONSENSUS_AGENT_ID   BAND_GOVERNANCE_AGENT_ID

# PostgreSQL (Zone 1)
POSTGRES_USER  POSTGRES_PASSWORD  POSTGRES_DB  PII_DB_DSN

# Auth
JWT_SECRET     # generate: python -c "import secrets; print(secrets.token_hex(32))"
```

Never commit `.env` — it is in `.gitignore`. See `.env.example` for full documentation of every variable.

### 2. Build

```bash
docker compose build
```

Builds `brightuity:latest` (backend + all agents) and the `frontend` nginx image.

### 3. Run

```bash
docker compose up
```

Services start in dependency order: PostgreSQL → PII seed → PII gateway + Consensus Signer → egress proxy → Band agents → backend → frontend.

| Service | URL |
|---|---|
| Frontend (React SPA) | <http://localhost> |
| Backend API | <http://localhost:8000> |
| Health check | <http://localhost:8000/health> |

### 4. Trigger a case

**Via the frontend:** log in → select a pending case from the dashboard → click **Start Processing** → watch the Band coordination room → review the Decision Evidence Package → Approve or Reject.

**Via curl:**

```bash
# Start the compliance pipeline
curl -X POST http://localhost:8000/cases/REQ-2041/run

# Poll pipeline status
curl http://localhost:8000/cases/REQ-2041/status

# Retrieve the Decision Evidence Package (after pipeline completes)
curl http://localhost:8000/cases/REQ-2041/package
```

---

## Demonstrated Outcomes

Two cases anchor the demo and prove both decision paths. Both are processed dynamically from the live database — not from hardcoded scripts.

### Marcus Weber — REQ-2041 · Commercial Real Estate (DE) · €2.50M · APPROVE

All five gates cleared with no exceptions. Consensus Signer issued seal **DGP-7F3A-2041**. Asset Tokenizer proposed 2,500 ERC-3643 tokens at €1,000 each with KYC-gated transfers and governance encoded. Head of Digital Assets authorized. Full APPROVE path confirmed end-to-end, evidence package sealed.

### Viktor Petrov — REQ-2043 · PEP Flag · HALT (no seal issued)

KYC Guardian detected a politically exposed person flag. Hard governance halt triggered by the Orchestrator — pipeline stopped before token structuring began. Consensus Signer was never invoked; no DGP seal was issued. Demonstrates that the governance gate is unconditional: no agent, including the Orchestrator, can bypass a halt verdict.

---

## Project Status

### Complete

- FastAPI backend: full case lifecycle API — `/cases`, `/cases/{id}/run`, `/cases/{id}/status`, `/cases/{id}/package`, `/cases/{id}/authorize`, `/cases/{id}/band-messages`, `/cases/{id}/evidence.pdf`
- Band coordination: real Band API integration; all 6 agent adapters live; @mention routing confirmed; backend context-visibility plumbing (`BAND_BACKEND_AGENT_ID` mentions)
- Both decision paths tested end-to-end: approve path (ECDSA seal issued) and halt path (seal correctly withheld)
- Zoned Docker Compose: 4 network zones, Squid egress proxy, PostgreSQL PII database, named volumes, health checks
- RAG corpus: ChromaDB index of MiCA and AMLD5 provisions — built, embedded, queryable
- 4-page React frontend: Login → Dashboard (live queue, auto-refresh on nav/focus/interval) → Band Room (raw live agent messages, real-time poll) → Review (Decision Evidence Package + human authorization)
- nginx production config: SPA routing + `/api/` reverse proxy; `frontend` service in Compose

### In Progress

- Demo recording and pitch deck for hackathon submission
- Production deploy to Vultr VPS

---

## Future Vision

The same Band-coordinated multi-agent architecture extends naturally to other bank divisions — AML investigations, credit underwriting, trade finance document chains — wherever compliance requires multiple specialist opinions converging on a single human decision. Brightuity is the coordination pattern; the agents are the specialties.

---

## Repository Structure

```
Brightuity/
├── frontend/               React + Vite + Three.js SPA
│                           Dockerfile.web, nginx.conf (production)
├── backend/                FastAPI gateway, band_bridge, case_store,
│                           pdf_renderer, authorization_signer
├── agents/                 Agent logic modules:
│                             orchestrator/, doc_auditor/, kyc_guardian/,
│                             dynamic_compliance/, stress_test/,
│                             asset_tokenizer/, consensus_signer/,
│                             governance_audit/, pii_gateway/
├── band_agents/            Band SDK adapters — run_*.py + *_adapter.py
│                           (one per agent)
├── database/               brightuity_clients.json (100 synthetic clients),
│                           seed scripts, PostgreSQL schema
├── rag_corpus/             MiCA + AMLD5 provisions, ChromaDB index,
│                           build_index.py
├── shared/                 LLM call wrapper (failover logic), Band client,
│                           config
├── infra/egress_proxy/     Squid Dockerfile + squid.conf (allow-list)
├── docs/                   Architecture and agent specification
├── docker-compose.yml      Multi-service compose with full zone isolation
├── Dockerfile              Main image (backend + all agents)
└── .env.example            Environment variable template
                            (copy to .env, fill values, never commit)
```

---

## License & Credits

**MIT License** — see [LICENSE](LICENSE).

Built by **Nevine Fakhreddin** ([@NevineAKF](https://github.com/NevineAKF)) — solo submission for the Band of Agents Hackathon (lablab.ai, June 2026, Track 3: Regulated & High-Stakes Workflows).

> *Tokenize the Real World. Unlock Infinite Liquidity.*
