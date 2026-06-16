-- =============================================================================
-- 03_ddl_stage_exchange_rate.sql — Stage table for Frankfurter exchange rates
-- Schema: stage
--
-- Landing zone: raw TEXT values from Frankfurter API v2 (CSV endpoint).
-- Format: one row per (date, base, quote) pair returned by the API.
-- Typed cleansing and vnd_per_usd derivation happen at ODS layer.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage.stage_exchange_rate (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rate_date       TEXT NOT NULL,
    base_currency   TEXT NOT NULL,
    quote_currency  TEXT NOT NULL,
    rate            TEXT NOT NULL,
    source_system   TEXT NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_exchange_rate_date
    ON stage.stage_exchange_rate (rate_date);

CREATE INDEX IF NOT EXISTS idx_stage_exchange_rate_batch
    ON stage.stage_exchange_rate (batch_id);
