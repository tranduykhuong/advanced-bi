-- =============================================================================
-- 02_ddl_nds_exchange_rate.sql — NDS table for exchange rates (3NF)
-- Schema: nds
-- =============================================================================

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
