-- =============================================================================
-- Migration 009: DDS Full Schema
-- Applies the complete Dimensional Data Store (DDS) star schema to the database.
--
-- Execution order respects FK dependencies:
--   dim_time → dim_currency → dim_country → dim_product → dim_fta
--   → dim_fta_country (bridge)
--   → fact_exchange_rate → fact_trade_transaction
--
-- All statements use IF NOT EXISTS / ON CONFLICT so this script is idempotent.
-- Safe to re-run on an existing database.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. dds.dim_time
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_time (
    time_key    INTEGER      NOT NULL,
    year        SMALLINT     NOT NULL,
    quarter     SMALLINT     NOT NULL    CHECK (quarter BETWEEN 1 AND 4),
    month       SMALLINT     NOT NULL    CHECK (month   BETWEEN 1 AND 12),

    CONSTRAINT pk_dds_dim_time PRIMARY KEY (time_key),
    CONSTRAINT uq_dds_dim_time_year_month UNIQUE (year, month)
);

COMMENT ON TABLE  dds.dim_time IS 'Conformed monthly time dimension. time_key = year*100+month.';
COMMENT ON COLUMN dds.dim_time.time_key IS 'Surrogate key: year*100 + month (e.g. 202301).';

-- ---------------------------------------------------------------------------
-- 2. dds.dim_currency
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_currency (
    currency_key    SERIAL       NOT NULL,
    currency_code   CHAR(3)      NOT NULL,
    currency_name   VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_currency      PRIMARY KEY (currency_key),
    CONSTRAINT uq_dds_dim_currency_code UNIQUE (currency_code)
);

INSERT INTO dds.dim_currency (currency_code, currency_name)
VALUES
    ('VND', 'Vietnamese Dong'),
    ('USD', 'United States Dollar')
ON CONFLICT (currency_code) DO NOTHING;

COMMENT ON TABLE dds.dim_currency IS 'Conformed currency dimension. Seeded with VND and USD.';

-- ---------------------------------------------------------------------------
-- 3. dds.dim_country  (SCD Type 2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_country (
    country_key     BIGSERIAL    NOT NULL,
    country_code    CHAR(3)      NOT NULL,
    country_name    TEXT,
    continent       TEXT,
    region          TEXT,
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,
    valid_from      DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to        DATE         NOT NULL DEFAULT '9999-12-31',
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_country PRIMARY KEY (country_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_country_current
    ON dds.dim_country (country_code)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_country_code
    ON dds.dim_country (country_code);

COMMENT ON TABLE  dds.dim_country IS 'SCD Type 2 country dimension. One is_current=TRUE row per country_code.';
COMMENT ON COLUMN dds.dim_country.version    IS 'Increments with each SCD2 change.';
COMMENT ON COLUMN dds.dim_country.valid_from IS 'Date this version became active.';
COMMENT ON COLUMN dds.dim_country.valid_to   IS '9999-12-31 for the current active version.';

-- ---------------------------------------------------------------------------
-- 4. dds.dim_product  (SCD Type 1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_product (
    product_key     BIGSERIAL    NOT NULL,
    hs_code         VARCHAR(8)   NOT NULL,
    hs_version      VARCHAR(10)  NOT NULL DEFAULT 'HS2017',
    hs_chapter      CHAR(2),
    hs_heading      CHAR(4),
    chapter_name    TEXT,
    heading_name    TEXT,
    product_name    TEXT,
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_product    PRIMARY KEY (product_key),
    CONSTRAINT uq_dds_dim_product_bk UNIQUE (hs_code, hs_version)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_chapter
    ON dds.dim_product (hs_chapter);

ALTER TABLE dds.dim_product ADD COLUMN IF NOT EXISTS hs_heading CHAR(4);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_heading
    ON dds.dim_product (hs_heading);

COMMENT ON TABLE  dds.dim_product IS 'SCD Type 1 product dimension keyed on (hs_code, hs_version).';
COMMENT ON COLUMN dds.dim_product.version IS 'Increments each time any attribute is overwritten (SCD1).';

-- ---------------------------------------------------------------------------
-- 5. dds.dim_fta  (SCD Type 1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_fta (
    fta_key         SERIAL       NOT NULL,
    fta_bk          UUID         NOT NULL,
    fta_name        TEXT,
    fta_code        VARCHAR(50),
    agreement_type  TEXT,
    scope           TEXT,
    enforcement_year INTEGER,
    status          TEXT,
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_fta    PRIMARY KEY (fta_key),
    CONSTRAINT uq_dds_dim_fta_bk UNIQUE (fta_bk)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_status
    ON dds.dim_fta (status);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_enforcement_year
    ON dds.dim_fta (enforcement_year);

COMMENT ON TABLE  dds.dim_fta IS 'SCD Type 1 Free Trade Agreement dimension.';
COMMENT ON COLUMN dds.dim_fta.fta_bk IS 'Business key — references nds.fta.fta_id.';

-- ---------------------------------------------------------------------------
-- 6. dds.dim_fta_country  (Bridge)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_fta_country (
    fta_key         INTEGER      NOT NULL,
    country_key     BIGINT       NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_fta_country PRIMARY KEY (fta_key, country_key),
    CONSTRAINT fk_dds_fta_country_fta
        FOREIGN KEY (fta_key)     REFERENCES dds.dim_fta     (fta_key),
    CONSTRAINT fk_dds_fta_country_country
        FOREIGN KEY (country_key) REFERENCES dds.dim_country (country_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_country_country
    ON dds.dim_fta_country (country_key);

COMMENT ON TABLE dds.dim_fta_country IS
    'Bridge table: FTA × member country. '
    'Replaces the flat text partner_countries field in the raw image schema.';

-- ---------------------------------------------------------------------------
-- 7. dds.fact_exchange_rate
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_exchange_rate (
    rate_key            BIGSERIAL      NOT NULL,
    time_key            INTEGER        NOT NULL,
    base_currency_key   INTEGER        NOT NULL,
    quote_currency_key  INTEGER        NOT NULL,
    rate_date           DATE           NOT NULL,
    rate_raw            NUMERIC(18,10) NOT NULL,
    exchange_rate       NUMERIC(18,6)  NOT NULL,
    source_system       VARCHAR(50)    NOT NULL DEFAULT 'FRANKFURTER',
    batch_id            UUID,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_fact_exchange_rate PRIMARY KEY (rate_key),
    CONSTRAINT uq_dds_fact_exchange_rate_grain
        UNIQUE (rate_date, base_currency_key, quote_currency_key),
    CONSTRAINT fk_dds_fact_exrate_time
        FOREIGN KEY (time_key)           REFERENCES dds.dim_time     (time_key),
    CONSTRAINT fk_dds_fact_exrate_base
        FOREIGN KEY (base_currency_key)  REFERENCES dds.dim_currency (currency_key),
    CONSTRAINT fk_dds_fact_exrate_quote
        FOREIGN KEY (quote_currency_key) REFERENCES dds.dim_currency (currency_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_fact_exrate_time_key
    ON dds.fact_exchange_rate (time_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_exrate_rate_date
    ON dds.fact_exchange_rate (rate_date);

COMMENT ON TABLE  dds.fact_exchange_rate IS
    'Daily exchange rate fact. Grain: rate_date × base_currency × quote_currency. '
    'exchange_rate = vnd_per_usd; rate_raw is the original Frankfurter value.';
COMMENT ON COLUMN dds.fact_exchange_rate.rate_raw      IS 'Raw rate from Frankfurter API.';
COMMENT ON COLUMN dds.fact_exchange_rate.exchange_rate IS 'vnd_per_usd = 1 / rate_raw. Used for trade value conversion.';

-- ---------------------------------------------------------------------------
-- 8. dds.fact_trade_transaction
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_trade_transaction (
    trade_key       BIGSERIAL    NOT NULL,
    time_key        INTEGER      NOT NULL,
    product_key     BIGINT       NOT NULL,
    partner_key     BIGINT       NOT NULL,
    fta_keys        INTEGER[],
    flow_type       BOOLEAN      NOT NULL,
    record_source   VARCHAR(20),
    value           NUMERIC(18,6),
    quantity        NUMERIC(18,6),
    unit            VARCHAR(20),
    value_vnd       NUMERIC(18,2),
    source_system   VARCHAR(50)  NOT NULL,
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_fact_trade PRIMARY KEY (trade_key),
    CONSTRAINT uq_dds_fact_trade_grain
        UNIQUE (time_key, product_key, partner_key, flow_type, record_source),
    CONSTRAINT fk_dds_fact_trade_time
        FOREIGN KEY (time_key)    REFERENCES dds.dim_time    (time_key),
    CONSTRAINT fk_dds_fact_trade_product
        FOREIGN KEY (product_key) REFERENCES dds.dim_product (product_key),
    CONSTRAINT fk_dds_fact_trade_partner
        FOREIGN KEY (partner_key) REFERENCES dds.dim_country (country_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_fact_trade_time_key
    ON dds.fact_trade_transaction (time_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_trade_partner_key
    ON dds.fact_trade_transaction (partner_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_trade_product_key
    ON dds.fact_trade_transaction (product_key);

CREATE INDEX IF NOT EXISTS ix_dds_fact_trade_flow_type
    ON dds.fact_trade_transaction (flow_type);

CREATE INDEX IF NOT EXISTS ix_dds_fact_trade_fta_keys
    ON dds.fact_trade_transaction USING GIN (fta_keys);

COMMENT ON TABLE  dds.fact_trade_transaction IS
    'Central star fact. Grain: time × product × partner × flow_type × record_source. '
    'value_vnd pre-computed at ETL load time using month-end VND/USD rate.';
COMMENT ON COLUMN dds.fact_trade_transaction.flow_type IS 'TRUE = Export, FALSE = Import.';
COMMENT ON COLUMN dds.fact_trade_transaction.fta_keys  IS 'Array of dim_fta.fta_key for FTAs utilised in this trade.';
COMMENT ON COLUMN dds.fact_trade_transaction.value_vnd IS 'Pre-computed: value (USD) × month-end vnd_per_usd.';
