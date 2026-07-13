-- Migration 007: exchange rate schema
-- Adds stage, ODS, and NDS tables for daily VND/USD rates from Frankfurter API.
-- All statements use IF NOT EXISTS / ON CONFLICT so this script is idempotent.

-- ---------------------------------------------------------------------------
-- stage.stage_exchange_rate — raw landing zone
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- ods.exchange_rate — typed, integrated (Inmon)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.exchange_rate (
    rate_date       DATE         NOT NULL,
    base_currency   CHAR(3)      NOT NULL DEFAULT 'VND',
    quote_currency  CHAR(3)      NOT NULL DEFAULT 'USD',
    rate            NUMERIC(18,10) NOT NULL,
    vnd_per_usd     NUMERIC(18,6)  NOT NULL,
    source_system   VARCHAR(50)  NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ods_exchange_rate UNIQUE (rate_date, base_currency, quote_currency)
);

CREATE INDEX IF NOT EXISTS idx_ods_exchange_rate_date
    ON ods.exchange_rate (rate_date);

-- Extend watermark table to support FRANKFURTER delta tracking.
-- etl_watermark primary key is source_system; the INSERT is idempotent.
INSERT INTO ods.etl_watermark (source_system, max_period_year, last_updated)
VALUES ('FRANKFURTER', 1999, NOW())
ON CONFLICT (source_system) DO NOTHING;

-- Add month granularity to the watermark so late-arriving detection for trade
-- sources (TRADE_MAP, NSO, UN_COMTRADE) can compare (year, month) instead of
-- year alone. Safe to re-run: ADD COLUMN IF NOT EXISTS is idempotent.
ALTER TABLE ods.etl_watermark
    ADD COLUMN IF NOT EXISTS max_period_month SMALLINT;

-- ---------------------------------------------------------------------------
-- nds.currency — master currency reference (3NF)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.currency (
    currency_code   CHAR(3)      NOT NULL,
    currency_name   VARCHAR(100),

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_currency PRIMARY KEY (currency_code)
);

-- Seed the two currencies used for trade value conversion.
INSERT INTO nds.currency (currency_code, currency_name)
VALUES
    ('VND', 'Vietnamese Dong'),
    ('USD', 'United States Dollar')
ON CONFLICT (currency_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- nds.exchange_rate — normalized daily rate reference (3NF)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.exchange_rate (
    rate_date       DATE         NOT NULL,
    base_currency   CHAR(3)      NOT NULL,
    quote_currency  CHAR(3)      NOT NULL,
    rate            NUMERIC(18,10) NOT NULL,
    vnd_per_usd     NUMERIC(18,6)  NOT NULL,
    source_system   VARCHAR(50)  NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_exchange_rate PRIMARY KEY (rate_date, base_currency, quote_currency),
    CONSTRAINT fk_nds_exchange_rate_base
        FOREIGN KEY (base_currency) REFERENCES nds.currency (currency_code),
    CONSTRAINT fk_nds_exchange_rate_quote
        FOREIGN KEY (quote_currency) REFERENCES nds.currency (currency_code)
);

CREATE INDEX IF NOT EXISTS idx_nds_exchange_rate_date
    ON nds.exchange_rate (rate_date);
