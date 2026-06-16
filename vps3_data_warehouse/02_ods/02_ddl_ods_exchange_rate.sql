-- =============================================================================
-- 02_ddl_ods_exchange_rate.sql — ODS table for exchange rates (Inmon)
-- Schema: ods
--
-- Design rules for this layer:
--   • Typed columns — promoted from stage after cleansing.
--   • Natural business key: (rate_date, base_currency, quote_currency).
--   • vnd_per_usd is a derived convenience column: 1 / rate.
--   • grain: one row per trading day × currency pair.
--
-- Source: Frankfurter API v2 via stage.stage_exchange_rate.
-- =============================================================================

CREATE TABLE IF NOT EXISTS ods.exchange_rate (
    rate_date       DATE         NOT NULL,
    base_currency   CHAR(3)      NOT NULL DEFAULT 'VND',
    quote_currency  CHAR(3)      NOT NULL DEFAULT 'USD',
    rate            NUMERIC(18,10) NOT NULL,   -- 1 base = rate quote (e.g. 1 VND = 3.9e-05 USD)
    vnd_per_usd     NUMERIC(18,6)  NOT NULL,   -- 1 USD = vnd_per_usd VND (1 / rate)
    source_system   VARCHAR(50)  NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ods_exchange_rate UNIQUE (rate_date, base_currency, quote_currency)
);

CREATE INDEX IF NOT EXISTS idx_ods_exchange_rate_date
    ON ods.exchange_rate (rate_date);
