# BRIGHTUITY — MASTER BUILD BLUEPRINT
### The single source of truth. Every puzzle piece of the system, how it fits, and how we build it.
*Give this file to any new session that loses context. It restores the entire picture.*

**Project:** Brightuity · **Hackathon:** Band of Agents (lablab.ai, June 12–19 2026) · **Track 3:** Regulated & High-Stakes Workflows
**Builder:** Nevine AKF (solo) · **GitHub:** github.com/NevineAKF/Brightuity (public, MIT) · **IDE:** VS Code · **Goal:** 1st place overall + AI/ML API partner prize

---

## 0. HOW TO USE THIS FILE
This is the blueprint of a complex puzzle mounted on a wall. Each piece = one system component (frontend, backend, database, API gateway, agents + their minds, Band layer, security, settlement). When a session forgets, re-read this top-to-bottom. The build order is in Section 9. Nothing here is decoration — every choice was deliberated and locked.

---

## 1. WHAT BRIGHTUITY IS (locked definition — do not reword)
Brightuity is an **enterprise B2B (vendor) system** for the **Digital Assets & Tokenization Division** of banks and financial institutions. It automates the compliance and verification pipeline that turns a real-world asset (property, gold, securities) into a tradeable digital token — replacing weeks of fragmented specialist work with a coordinated team of seven AI agents, while final approval always stays with a human (the Head of Digital Assets).

**One line:** Seven AI agents. One human decision. Complete auditability.
**Tagline:** Tokenize the Real World. Unlock Infinite Liquidity.
**Descriptor:** RWA Tokenization Intelligence.

**Legal positioning (critical, keep consistent):** Brightuity is a **technology vendor**, NOT a bank or licensed entity. The client bank is the licensed party and runs Brightuity under its own licenses → Nevine bears no regulatory liability. But because it is built FOR a regulated entity, the system must be designed to understand and respect real legal/regulatory procedure. Always keep the words "business / B2B" and "Digital Assets & Tokenization Division."

---

## 2. THE PROBLEM IT SOLVES (the "why")
Issuing a token takes minutes. Proving an asset + owner are legitimate enough to tokenize takes weeks. **The bottleneck is not the blockchain — it is the coordination of compliance.** A request queues across a document specialist → KYC officer → compliance lawyer (multi-jurisdiction) → risk analyst → structuring engineer, each in a different tool, each re-explaining, each handoff bleeding time and context.

**Verified facts (use these exact numbers):**
- RWA on-chain market surpassed **$25B early 2026** ($25–36B range), ~4x YoY. Led by JPMorgan, HSBC, Franklin Templeton, BlackRock.
- ~**$450 trillion** global tokenizable assets. McKinsey: $2T by 2030 (conservative); BCG: $16T by 2030.
- Corporate onboarding up to **100 days**, 40%+ on KYC (Trulioo). One KYC review **$1,500–$3,500**; 10k clients/yr → up to **$35M** on KYC alone (Fenergo). **90%** of banks say manual KYC error potential affects risk decisions (Fenergo). AML enforcement **$4.6B in 2024** (Docusign).

**Core insight:** the bottleneck is not expertise — it is the *coordination* of expertise.

---

## 3. THE SEVEN AGENTS (THE MINDS) — primary + automatic fallback
Each agent = one veteran human specialist. One agent, one specialty. Every LLM agent has a PRIMARY model and an automatic silent FALLBACK. The 7th has no model by design.

| # | Agent | Framework | PRIMARY model | FALLBACK model | Platform |
|---|---|---|---|---|---|
| 1 | Orchestrator 🎯 | CrewAI | Claude Opus 4.8 | Claude Sonnet 4.6 | AI/ML API |
| 2 | Doc Auditor 📄 | Python | Qwen 3.6 | Gemma-4 | Featherless |
| 3 | KYC Guardian 🛡️ | Python | Claude Opus 4.8 | GPT (latest) | AI/ML API |
| 4 | Dynamic Compliance ⚖️ | LangChain + RAG | **Gemini 3.1 Pro** | GPT (latest) | AI/ML API |
| 5 | Stress-Test Simulator 📈 | Python | DeepSeek-V4-Pro | Qwen 3.6 | Featherless |
| 6 | Asset Tokenizer 🪙 | Python | Kimi-K2.6 | GLM 4.6 | Featherless |
| 7 | Consensus Signer 🔐 | Pure Python | NO LLM (ECDSA) | — | — |

**Role of each:**
1. **Orchestrator** — reads each case, decides dynamically which agent to engage and in what order, enforces governance gates, compiles final report. The busiest agent.
2. **Doc Auditor** — examines deeds, valuations, registry filings; extracts fields; flags missing/suspicious docs. First gate.
3. **KYC Guardian** — identity verification, sanctions/PEP screening, source-of-funds. Most sensitive agent; can trigger a hard halt. (Cross-family fallback = platform redundancy.)
4. **Dynamic Compliance** — maps case to jurisdiction (MiCA/FCA/VARA), issues opinion grounded in RAG over real regulatory texts (never memory). Long context essential (MiCA ~200 pages).
5. **Stress-Test Simulator** — fair value, risk score 0–100, scenario stress (downturn, rate shock, liquidity).
6. **Asset Tokenizer** — designs token structure: supply, unit price, ERC-3643 class, transfer restrictions, governance.
7. **Consensus Signer** — NO LLM by design. Verifies all gates cleared (Doc✓ KYC✓ Compliance✓ Risk✓ Tokenizer✓), hashes the canonical record, signs with ECDSA. Tamper-evident "Deterministic Gateway Proof." Answers "how do you certify a non-deterministic system?" → probabilistic intelligence analyzes; deterministic code seals.

**IMPORTANT — Fable 5 history:** Compliance originally used Claude Fable 5. On June 12 2026 a US export-control directive suspended Fable 5/Mythos 5 for all users. Gemini 3.1 Pro (its designated long-context fallback) was promoted to primary by changing one line. This is now a SELLING POINT: real failover proven live, not theoretical.

**Platform split:** AI/ML API = sensitive 3 (Orchestrator, KYC, Compliance) → qualifies partner prize, $10 credit is enough. Featherless = analytical 3 (Doc, Risk, Tokenizer) → won $500 credits + sovereign-ready story.

---

## 4. AUTOMATIC FAILOVER (zero human intervention) — infrastructure logic, NOT decision logic
Shared wrapper `call_agent_model(agent, prompt)`:
1. Try PRIMARY (timeout 30s; invalid/empty = failure).
2. On failure: retry PRIMARY once.
3. On 2nd failure: switch to FALLBACK silently — same prompt, same output contract.
4. Log switchover (agent, models, error, timestamp) to audit record.
5. If FALLBACK also fails: agent reports structured error to Orchestrator via Band → escalates to human.
Triggers: API errors, timeouts, rate limits, **exhausted credits**, malformed responses.

**CRITICAL DISTINCTION (Nevine stressed this):** Failover is FIXED infrastructure (fine to be deterministic). But agent **DECISIONS must be dynamic** — driven by each client's real data, never a hardcoded script. Outcomes EMERGE from the database. The Orchestrator chooses the path per case. NO scripted scenario. Proof-of-life: a judge can pick ANY of the 100 clients and the system processes it live.

---

## 5. THE SECURITY MODEL (Hybrid Isolation — the differentiator)
Classification: **on-premise embedded enterprise system, zoned architecture, controlled egress, data-diode pattern.** Explicitly NOT "air-gap" (it connects to internet for Band + APIs — claiming air-gap would be false and lose credibility). Honesty = credibility.

Three zones:
- **Zone 1 — Bank Perimeter (isolated):** DB1 (PII, KYC, documents) + the 7 agents in Docker containers. DB1 has NO internet route. Agents read PII locally.
- **Zone 2 — Coordination (external, Band):** carries only task IDs, @mentions, verdicts — NEVER PII or documents. Band sees that work happens, never what it contains. The coordination log IS the audit trail.
- **Zone 3 — Enrichment (external, inbound-only):** DB2 (market data, news, regulatory updates). One-way gateway (data-diode): info IN, customer data NEVER out.

Standards: "architected in alignment with ISO 27001 / SOC 2 / DORA principles — certification-ready" (NOT certified). Implements banking control principles. Web scraping DEFERRED to future version — production uses licensed providers (Bloomberg, Reuters/LSEG, CoreLogic). "Source-agnostic."

Bounded autonomy **Level 3**: Orchestrator decides order/strategy dynamically, but hard governance gates never break (no token before KYC + Compliance clear; anomalies escalate).

---

## 6. THE WEBSITE (THE FACE) — 3 pages, already built as React, navy #0A1A2F + gold #E8A93D, Montserrat, hexagon logo
**Must be a real, professional, bank-grade website — not a prototype.** Dark mode.

**Page 1 — Login:** vault-unlock animation (lock opens on credentials). User: **Nevine AKF, Head of Digital Assets**. (Built: brightuity-login.jsx + brightuity-vault-login.jsx)

**Page 2 — Dashboard:** pending requests as living interactive cards (not a static table) — each with: randomuser photo (as if extracted from official ID), lock + verified badge, encrypted doc ID, request ID, client name, country, asset type, asset value. **Living queue:** state must update each session based on what was/wasn't processed (pending → processed; new ones arrive). NOT random — governed by lifecycle. (Built: brightuity-dashboard.jsx)

**Page 3 — Review (three-panel):**
- **LEFT:** Band chat — @mentions appear one-by-one with 1–2s delay (Orchestrator delegates, each agent replies with verdict, encrypted refs). THIS WINDOW IS THE PROOF of Band coordination = judging criterion #1.
- **CENTER:** asset-to-token visual — 3D metallic hexagonal token (Three.js), state-reactive: silver/spinning while processing → gold glowing on completion → dark-red frozen on halt. Mouse parallax, orbiting particles, energy-flow animation (gold pulse flows into active verdict card), mini rotating gears by status badge.
- **RIGHT:** 6 verdict cards with latency indicators + Export PDF + Forward-to-department dropdown (Legal / Management / etc.).
- **BOTTOM:** decision zone — system recommendation + human Approve/Reject + mandatory reason + e-signature; full audit-trail modal after signing.
- **Two demo scenarios:** Case A Marcus Weber (REQ-2041, approve) · Case B Viktor Petrov (REQ-2043, PEP rejection, hard governance halt). (Built: brightuity-review.jsx)
- *(Note: a full-width "system pulse bar" was built then removed as redundant.)*

---

## 7. THE DATA (THE FUEL) — DONE
**Meridian Digital Bank** — fictional EU digital bank under MiCA. 100 synthetic clients (generated, validated, in outputs).
- 12 EU countries, gender-matched randomuser photos, unique names / passport formats / encrypted doc IDs (SHA-256) / request IDs.
- Latent distribution (agents DISCOVER, not scripted): 75 clean / 10 doc-issue / 8 PEP-sanctions / 7 high-risk.
- Living lifecycle: pending / processed-history / not_yet_arrived. Governance-consistent history (no gated client ever "approved").
- 3 anchors: Marcus Weber REQ-2041 (approve), Sofia Andreou REQ-2042 (doc-issue), Viktor Petrov REQ-2043 (PEP reject).
- Files: `brightuity_clients.json` + `seed_database.py` (seed=42, reproducible).
- In production this connects to the bank's real customer DB.

---

## 8. TECH STACK (THE MATERIALS)
| Layer | Technology |
|---|---|
| Frontend | React (navy/gold, Montserrat, Three.js for 3D token) |
| Backend | FastAPI (Python) |
| Databases | PostgreSQL ×2 (DB1 isolated PII / DB2 enrichment) |
| Coordination | Band SDK/API (chat rooms, @mentions) — commercial, free tier confirmed |
| Agent frameworks | CrewAI (Orchestrator) + LangChain+RAG (Compliance) + plain Python (rest) |
| Models | AI/ML API (sensitive) + Featherless (analytical) |
| Crypto | Python `ecdsa`/`cryptography` (Consensus Signer, ~30 lines) |
| Containerization | Docker Compose (one container per agent = isolation story) |
| Hosting | Vultr (pay-as-you-go; ~$7–10 for whole hackathon) |
| Data gen | randomuser.me + Faker + real property values |

**Cross-framework is intentional** (CrewAI + LangChain + Python) → proves Band coordinates across frameworks = criterion #1.

---

## 9. BUILD ORDER (THE ASSEMBLY SEQUENCE)
**Phase 0 — Setup (NOW, no Band needed):** ✅ GitHub repo linked to VS Code (done). ✅ 100-client DB done. Next: create folder structure; drop in DB + frontend files.
**Phase 1 — Pre-kickoff prep:** agent system prompts (expert persona each); RAG corpus (real MiCA/AML texts) for Compliance; Consensus Signer ECDSA (~30 lines, no Band needed).
**Phase 2 — On Band access (days 1–3):** read Band docs; test 2-agent room; build 7 agents + Band wiring (@mentions); FastAPI backend (Frontend ↔ Band ↔ DB1/DB2).
**Phase 3 — Integration (days 4–5):** connect approved frontend to real backend; DB2 enrichment; proof-of-life testing (random client). Optional polish.
**Phase 4 — Submission (days 6–7):** intro video (brightuity-intro.html done) + demo recording (script done) + pitch deck + submit. Required: public GitHub repo, app URL (Vultr), video, slides.

---

## 10. FOLDER STRUCTURE (proposed)
```
Brightuity/
├── README.md, LICENSE, .gitignore        (done)
├── frontend/        React app (login, dashboard, review pages)
├── backend/         FastAPI (api gateway, auth, case state, Band bridge)
├── agents/          7 agents: orchestrator/, doc_auditor/, kyc_guardian/,
│                    dynamic_compliance/, stress_test/, asset_tokenizer/,
│                    consensus_signer/   (each: logic + system prompt + model config + fallback)
├── database/        seed_database.py, brightuity_clients.json, schema (DB1/DB2)
├── rag_corpus/      MiCA / AML / regulatory texts for Compliance agent
├── shared/          call_agent_model wrapper (failover), Band client, config
├── docker-compose.yml
└── docs/            architecture, agent spec, video script, diagrams
```

---

## 11. WORKFLOW (END TO END)
1. Client submits tokenization request (external portal) → 2. enters DB1 as "Pending" → 3. Head opens Brightuity, sees queue → 4. selects case, clicks "Initiate Review" → 5. Backend → Orchestrator via Band → agents collaborate → 6. agents read PII locally, enrich from DB2, post verdicts to Band → 7. Consensus Signer seals → report generated → 8. Head reviews, Approves/Rejects, e-signs → 9. approved → Settlement (token issued on permissioned chain); rejected → client notified + logged.

Blockchain = Settlement layer only (Asset Tokenizer + Consensus Signer). Core banking + PII stay off-chain. Smart-contract example: "If client transfers token value, instantly move the property share to their wallet and release funds to the seller — no lawyer, no notary, no intermediary."

---

## 12. CLAUDE CODE / CLI INTEGRATION (how Nevine wants to build)
Nevine will connect Claude Code (or similar agentic coding from inside VS Code) to generate files directly. Workflow discipline:
- Every change committed to GitHub (`git add . && git commit -m "..." && git push`).
- This blueprint is the spec the coding agent follows.
- When a coding session loses context, paste this file + say what's built and where (check Section 9 phase + Section 10 folders).

---

## 13. DECISIONS WE REJECTED (don't revisit)
- **Claude Managed Agents** — rejected (would undermine Band's coordination role, kill cross-framework story, disqualify partner prize, conflict with Featherless credits).
- **MCP** — evaluated, deferred. Mention as production vision only, NOT in hackathon build.
- **Web scraping** — deferred to future version; production uses licensed data providers.
- **Single-scenario hardcoding** — forbidden. Outcomes must emerge from data.
- **Literal "air-gap" claim** — rejected as technically false; use "network-isolation-boundary / data-segregation."

---

## 14. WINNING STRATEGY (what actually wins)
- Foreground the **Band coordination room** — it's criterion #1. The visible @mention conversation IS the proof.
- Make the **failure path** (Viktor PEP halt) central, not hidden — saying "no" correctly proves rigor.
- **Proof-of-life:** let judges pick any random client → proves not scripted.
- Have the **"why Band not function calls?"** answer ready: persistent auditable coordination log + cross-framework + emergent coordination.
- Tell the **Fable failover true story** — proves resilience is real.
- Target: **1st place overall + AI/ML API partner prize.**

---

*Built deliberately, piece by piece. This is the blueprint. Assemble with precision. — Brightuity*
