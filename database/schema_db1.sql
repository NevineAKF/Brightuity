-- =============================================================================
-- BRIGHTUITY — DB1 SCHEMA (ZONE 1)
-- Classification: ISOLATED · BANK PERIMETER · NO INTERNET ROUTE
-- This database runs inside Zone 1. No container outside Zone 1 may connect.
-- PII, KYC data, and all document references live exclusively here.
-- The expected_outcome column is an internal agent-training label — it must
-- never appear in any API response, Band message, or external log.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- clients
-- One row per tokenization applicant. Populated from seed_database.py;
-- in production this mirrors the bank's core client DB (read-only import).
-- ---------------------------------------------------------------------------
CREATE TABLE clients (
    client_id           VARCHAR(12)     PRIMARY KEY,            -- e.g. CLT-0001
    request_id          VARCHAR(12)     UNIQUE NOT NULL,         -- e.g. REQ-2041
    encrypted_doc_id    VARCHAR(20)     NOT NULL,               -- SHA-256 prefix shown on cards
    full_name           VARCHAR(200)    NOT NULL,
    gender              VARCHAR(10),
    nationality         VARCHAR(100),
    country_flag        VARCHAR(10),                            -- Unicode flag emoji
    date_of_birth       DATE,
    passport_number     VARCHAR(50),                            -- PII — Zone 1 only
    address             TEXT,                                   -- PII — Zone 1 only
    photo_url           TEXT,                                   -- randomuser.me portrait

    -- Asset fields
    asset_type          VARCHAR(100),   -- Commercial Property / Gold Reserve / etc.
    asset_detail        TEXT,
    asset_value_eur     BIGINT,

    -- Submission
    submitted_at        TIMESTAMP,
    status              VARCHAR(30)     NOT NULL DEFAULT 'pending',
                        -- pending | in_review | awaiting_decision | approved | rejected | not_yet_arrived

    -- Document audit (latent — discovered by Doc Auditor, never scripted)
    documents_status    VARCHAR(20),    -- complete | issues
    document_issues     JSONB           NOT NULL DEFAULT '[]',

    -- KYC audit (latent — discovered by KYC Guardian)
    kyc_status          VARCHAR(50),    -- clean | pep_match | sanctions_adjacent
    kyc_flags           JSONB           NOT NULL DEFAULT '[]',
    source_of_funds     TEXT,
    source_verifiable   BOOLEAN,

    -- Risk flags (latent — discovered by Stress-Test Simulator)
    risk_flags          JSONB           NOT NULL DEFAULT '[]',

    -- INTERNAL ONLY — agent training label, outcome distribution seeded at generation time.
    -- This field MUST NEVER be included in any API response, Band message, or external log.
    expected_outcome    VARCHAR(30),    -- approve | reject_documents | reject_kyc | reject_risk

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_clients_status      ON clients(status);
CREATE INDEX idx_clients_nationality ON clients(nationality);
CREATE INDEX idx_clients_submitted   ON clients(submitted_at DESC);

-- ---------------------------------------------------------------------------
-- cases
-- Lifecycle record for each review initiated by the Head of Digital Assets.
-- Separate from clients so that audit history survives status changes on the
-- client row and so multiple review attempts (if ever needed) are distinct.
-- ---------------------------------------------------------------------------
CREATE TABLE cases (
    id                  SERIAL          PRIMARY KEY,
    request_id          VARCHAR(12)     NOT NULL REFERENCES clients(request_id),
    status              VARCHAR(30)     NOT NULL DEFAULT 'pending',
                        -- pending | in_review | awaiting_decision | approved | rejected | halted

    -- Initiation
    initiated_by        VARCHAR(200),   -- Nevine AKF (Head of Digital Assets)
    initiated_at        TIMESTAMP,

    -- Agent verdicts (written by Orchestrator as each agent completes)
    agent_verdicts      JSONB           NOT NULL DEFAULT '{}',
    -- Schema of agent_verdicts:
    -- {
    --   "doc_auditor":         {"verdict": "pass|fail|halt", "summary": "...", "latency_ms": 0},
    --   "kyc_guardian":        {"verdict": "pass|fail|halt", "summary": "...", "latency_ms": 0},
    --   "dynamic_compliance":  {"verdict": "pass|fail|halt", "summary": "...", "latency_ms": 0},
    --   "stress_test":         {"verdict": "pass|fail|halt", "summary": "...", "latency_ms": 0},
    --   "asset_tokenizer":     {"verdict": "pass|fail|halt", "summary": "...", "latency_ms": 0},
    --   "consensus_signer":    {"verdict": "sealed|blocked",  "hash": "...",   "latency_ms": 0}
    -- }

    -- Consensus seal (written by Consensus Signer on successful completion)
    consensus_hash      VARCHAR(128),   -- SHA-256 of canonical case record
    ecdsa_signature     TEXT,           -- hex-encoded ECDSA signature
    sealed_at           TIMESTAMP,

    -- Human decision (written when Head approves/rejects)
    completed_at        TIMESTAMP,
    decision            VARCHAR(20),    -- approve | reject
    decision_reason     TEXT            NOT NULL DEFAULT '',
    decision_by         VARCHAR(200),
    esignature_hash     VARCHAR(128),   -- hash of typed e-signature string

    created_at          TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP       NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cases_request_id ON cases(request_id);
CREATE INDEX idx_cases_status     ON cases(status);

-- ---------------------------------------------------------------------------
-- audit_log
-- Append-only. Every system event — agent switchover, Band message sent,
-- human decision, status change — is recorded here.
-- No rows are ever updated or deleted. Compliance teams audit this table.
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id              BIGSERIAL       PRIMARY KEY,
    event_at        TIMESTAMP       NOT NULL DEFAULT NOW(),
    request_id      VARCHAR(12),                            -- NULL for non-case events
    actor           VARCHAR(200)    NOT NULL,               -- user name or agent identifier
    event_type      VARCHAR(100)    NOT NULL,
                    -- case.initiated | case.status_changed | agent.verdict
                    -- agent.model_switchover | band.message_sent | human.decision
                    -- consensus.sealed | auth.login | auth.logout
    event_detail    JSONB           NOT NULL DEFAULT '{}',  -- event-specific payload
    band_message_id TEXT,                                   -- Band message ID if applicable
    ip_address      VARCHAR(45)                             -- IPv4 or IPv6
);

CREATE INDEX idx_audit_request_id ON audit_log(request_id);
CREATE INDEX idx_audit_event_at   ON audit_log(event_at DESC);
CREATE INDEX idx_audit_event_type ON audit_log(event_type);

-- ---------------------------------------------------------------------------
-- Prevent accidental UPDATE / DELETE on audit_log (defence-in-depth)
-- Grant the application role SELECT + INSERT only; never UPDATE or DELETE.
-- In production: REVOKE UPDATE, DELETE ON audit_log FROM brightuity_app;
-- ---------------------------------------------------------------------------

COMMENT ON TABLE audit_log IS
    'Append-only compliance log. Never update or delete rows. '
    'Application role must have INSERT + SELECT only.';

COMMENT ON COLUMN clients.expected_outcome IS
    'INTERNAL ONLY. Agent-training distribution label. '
    'Must never appear in any API response, Band message, or external log.';
