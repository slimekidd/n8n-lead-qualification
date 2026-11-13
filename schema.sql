-- Leads table used by all four workflows.
-- Reconstructed from the queries in the workflows; adjust types to match your existing table if you already have one.

CREATE TABLE IF NOT EXISTS leads (
    id                    BIGSERIAL PRIMARY KEY,
    lead_id               TEXT NOT NULL UNIQUE,
    client_name           TEXT,
    company               TEXT,
    budget                NUMERIC,
    request               TEXT,

    -- lifecycle
    status                TEXT NOT NULL DEFAULT 'processing',   -- processing | completed | failed
    execution_id          TEXT,          -- n8n execution that currently owns the row
    parent_execution_id   TEXT,          -- Retry Processor execution that scheduled the retry
    processing_started_at TIMESTAMPTZ,
    processed_at          TIMESTAMPTZ,

    -- retries
    retry_count           INTEGER NOT NULL DEFAULT 0,
    next_retry_at         TIMESTAMPTZ,
    error_message         TEXT,

    -- idempotency flags
    sheets_saved          BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_sent         BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_message_id   TEXT,

    -- monitoring
    stuck_alert_sent_at   TIMESTAMPTZ,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS leads_retry_idx
    ON leads (status, next_retry_at) WHERE status = 'failed';

CREATE INDEX IF NOT EXISTS leads_stuck_idx
    ON leads (status, processing_started_at) WHERE status = 'processing';
