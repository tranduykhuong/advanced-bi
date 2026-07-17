-- =============================================================================
-- 01_ddl_dds.sql — Dimensional Data Store (DDS) Star Schema DDL
-- Schema: dds
--
-- Design rules for this layer (Kimball):
--   • Surrogate keys (integer sequences) on all dimension tables.
--   • SCD Type 2 on dds.dim_country, dds.dim_product, dds.dim_fta
--     (is_current / version / effective_date / expiry_date on all three —
--     new row + version+1 on change). fact_trade_transaction resolves the
--     dimension key valid AT THE TRADE'S OWN PERIOD (first day of the month)
--     via effective_date/expiry_date, not simply the current version — this
--     correctly links late-arriving facts to the dimension state that was
--     true at their time, per the late-arriving-fact technique.
--   • dds.dim_time is a conformed monthly calendar dimension.
--   • dds.dim_currency is a conformed currency dimension (seed: VND, USD).
--   • dds.dim_fta_country is a bridge table replacing the flat text partner_countries.
--   • dds.fact_trade grain: time × product × partner × flow_type × source_system.
--   • dds.fact_exchange_rate grain: rate_date × base_currency × quote_currency.
--
-- Source:  nds schema (nds.trade_transaction, nds.country, nds.product,
--                       nds.time, nds.fta, nds.fta_member, nds.fta_utilization,
--                       nds.exchange_rate, nds.currency)
-- ETL:     vps2_data_integration/03_load/nds_to_dds_scd.py
-- =============================================================================

-- ---------------------------------------------------------------------------
-- dds.dim_time  — conformed monthly calendar dimension
-- Surrogate key convention: year * 100 + month  (e.g. 202301 = Jan 2023)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_time (
    time_key    INTEGER      NOT NULL,   -- surrogate key: YYYYMM

    year        SMALLINT     NOT NULL,
    quarter     SMALLINT     NOT NULL    CHECK (quarter BETWEEN 1 AND 4),
    month       SMALLINT     NOT NULL    CHECK (month   BETWEEN 1 AND 12),

    CONSTRAINT pk_dds_dim_time PRIMARY KEY (time_key),
    CONSTRAINT uq_dds_dim_time_year_month UNIQUE (year, month)
);

COMMENT ON TABLE  dds.dim_time IS 'Conformed monthly time dimension. time_key = year*100+month.';
COMMENT ON COLUMN dds.dim_time.time_key IS 'Surrogate key: year*100 + month (e.g. 202301).';

-- ---------------------------------------------------------------------------
-- dds.dim_currency  — conformed currency dimension
-- Seeded with VND and USD; used as FK by fact_exchange_rate.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_currency (
    currency_key    SERIAL       NOT NULL,
    currency_code   CHAR(3)      NOT NULL,
    currency_name   VARCHAR(100),

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_currency     PRIMARY KEY (currency_key),
    CONSTRAINT uq_dds_dim_currency_code UNIQUE (currency_code)
);

-- Seed VND and USD (idempotent)
INSERT INTO dds.dim_currency (currency_code, currency_name)
VALUES
    ('VND', 'Vietnamese Dong'),
    ('USD', 'United States Dollar')
ON CONFLICT (currency_code) DO NOTHING;

COMMENT ON TABLE dds.dim_currency IS 'Conformed currency dimension. Seeded with VND and USD.';

-- ---------------------------------------------------------------------------
-- dds.dim_country  — SCD Type 2
-- Tracks historical changes to country attributes (name, region, continent).
-- A partial unique index enforces exactly one is_current = TRUE per country_code.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_country (
    country_key     BIGSERIAL    NOT NULL,   -- surrogate key

    -- Business key
    country_code    CHAR(3)      NOT NULL,   -- ISO-3166-1 alpha-3

    -- Descriptive attributes
    country_name    TEXT,
    continent       TEXT,
    region          TEXT,

    -- SCD2 tracking columns
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,

    -- Point-in-time validity range for late-arriving fact resolution.
    -- First version: effective_date = '-infinity' (no observed prior state).
    -- Later versions: effective_date = the date the change was detected.
    effective_date  DATE         NOT NULL DEFAULT '-infinity',
    expiry_date     DATE         NOT NULL DEFAULT 'infinity',

    -- Lineage
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_country PRIMARY KEY (country_key)
);

-- Retrofit: table may predate effective_date/expiry_date (added for
-- late-arriving fact resolution). No-op on fresh installs.
ALTER TABLE dds.dim_country
    ADD COLUMN IF NOT EXISTS effective_date DATE NOT NULL DEFAULT '-infinity',
    ADD COLUMN IF NOT EXISTS expiry_date    DATE NOT NULL DEFAULT 'infinity';

-- Partial unique index: only one active row per country_code
CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_country_current
    ON dds.dim_country (country_code)
    WHERE is_current = TRUE;

-- Index for SCD2 expire lookups
CREATE INDEX IF NOT EXISTS ix_dds_dim_country_code
    ON dds.dim_country (country_code);

-- Index for point-in-time fact resolution (country_code, [effective_date, expiry_date))
CREATE INDEX IF NOT EXISTS ix_dds_dim_country_validity
    ON dds.dim_country (country_code, effective_date, expiry_date);

COMMENT ON TABLE  dds.dim_country IS 'SCD Type 2 country dimension. One is_current=TRUE row per country_code.';
COMMENT ON COLUMN dds.dim_country.version    IS 'Increments with each SCD2 change.';

-- ---------------------------------------------------------------------------
-- dds.dim_product  — SCD Type 2
-- Tracks historical changes to product attributes (chapter/heading/name).
-- A partial unique index enforces exactly one is_current = TRUE per
-- (hs_code, hs_version).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_product (
    product_key     BIGSERIAL    NOT NULL,   -- surrogate key

    -- Business key
    hs_code         VARCHAR(8)   NOT NULL,   -- HS commodity code
    hs_version      VARCHAR(10)  NOT NULL DEFAULT 'HS2017',

    -- Descriptive attributes
    hs_chapter      CHAR(2),                 -- 2-digit chapter
    hs_heading      CHAR(4),
    chapter_name    TEXT,                    -- chapter description
    heading_name    TEXT,                    -- 4-digit heading description
    product_name    TEXT,                    -- full product name

    -- SCD2 tracking columns
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,

    -- Point-in-time validity range for late-arriving fact resolution.
    -- First version: effective_date = '-infinity' (no observed prior state).
    -- Later versions: effective_date = the date the change was detected.
    effective_date  DATE         NOT NULL DEFAULT '-infinity',
    expiry_date     DATE         NOT NULL DEFAULT 'infinity',

    -- Lineage
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_product     PRIMARY KEY (product_key)
);

-- Retrofit: table may predate effective_date/expiry_date. No-op on fresh installs.
ALTER TABLE dds.dim_product
    ADD COLUMN IF NOT EXISTS effective_date DATE NOT NULL DEFAULT '-infinity',
    ADD COLUMN IF NOT EXISTS expiry_date    DATE NOT NULL DEFAULT 'infinity';

-- Partial unique index: only one active row per (hs_code, hs_version)
CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_product_current
    ON dds.dim_product (hs_code, hs_version)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_bk
    ON dds.dim_product (hs_code, hs_version);

-- Index for point-in-time fact resolution ((hs_code,hs_version), [effective_date, expiry_date))
CREATE INDEX IF NOT EXISTS ix_dds_dim_product_validity
    ON dds.dim_product (hs_code, hs_version, effective_date, expiry_date);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_chapter
    ON dds.dim_product (hs_chapter);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_heading
    ON dds.dim_product (hs_heading);

COMMENT ON TABLE  dds.dim_product IS 'SCD Type 2 product dimension. One is_current=TRUE row per (hs_code, hs_version).';
COMMENT ON COLUMN dds.dim_product.version    IS 'Increments with each SCD2 change.';

-- ---------------------------------------------------------------------------
-- dds.dim_fta  — SCD Type 2
-- Free Trade Agreement reference. Historical changes to FTA attributes
-- (status, scope, enforcement_year, ...) are preserved as new versions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_fta (
    fta_key         SERIAL       NOT NULL,   -- surrogate key

    -- Business key (links back to nds.fta.fta_id)
    fta_bk          UUID         NOT NULL,

    -- Descriptive attributes
    fta_name        TEXT,
    fta_code        VARCHAR(50),             -- APTIAD number / short code
    agreement_type  TEXT,                    -- e.g. 'Bilateral', 'Multilateral'
    scope           TEXT,                    -- e.g. 'Goods', 'Services', 'Both'
    enforcement_year INTEGER,
    status          TEXT,                    -- e.g. 'In Force', 'Signed'

    -- SCD2 tracking columns
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE,
    version         INTEGER      NOT NULL DEFAULT 1,

    -- Point-in-time validity range for late-arriving fact resolution.
    -- First version: effective_date = '-infinity' (no observed prior state).
    -- Later versions: effective_date = the date the change was detected.
    effective_date  DATE         NOT NULL DEFAULT '-infinity',
    expiry_date     DATE         NOT NULL DEFAULT 'infinity',

    -- Lineage
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_fta    PRIMARY KEY (fta_key)
);

-- Retrofit: table may predate effective_date/expiry_date. No-op on fresh installs.
ALTER TABLE dds.dim_fta
    ADD COLUMN IF NOT EXISTS effective_date DATE NOT NULL DEFAULT '-infinity',
    ADD COLUMN IF NOT EXISTS expiry_date    DATE NOT NULL DEFAULT 'infinity';

-- Partial unique index: only one active row per fta_bk
CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_fta_current
    ON dds.dim_fta (fta_bk)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_bk
    ON dds.dim_fta (fta_bk);

-- Index for point-in-time fact resolution (fta_bk, [effective_date, expiry_date))
CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_validity
    ON dds.dim_fta (fta_bk, effective_date, expiry_date);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_status
    ON dds.dim_fta (status);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_enforcement_year
    ON dds.dim_fta (enforcement_year);

COMMENT ON TABLE  dds.dim_fta IS 'SCD Type 2 Free Trade Agreement dimension. One is_current=TRUE row per fta_bk.';
COMMENT ON COLUMN dds.dim_fta.fta_bk      IS 'Business key — references nds.fta.fta_id.';
COMMENT ON COLUMN dds.dim_fta.version     IS 'Increments with each SCD2 change.';

-- ---------------------------------------------------------------------------
-- dds.dim_fta_country  — Bridge table
-- Replaces the flat text partner_countries column with a proper FK bridge.
-- Each FTA can have many member countries; each country can belong to many FTAs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_fta_country (
    fta_key         INTEGER      NOT NULL,
    country_key     BIGINT       NOT NULL,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_fta_country PRIMARY KEY (fta_key, country_key),
    CONSTRAINT fk_dds_fta_country_fta
        FOREIGN KEY (fta_key)     REFERENCES dds.dim_fta (fta_key),
    CONSTRAINT fk_dds_fta_country_country
        FOREIGN KEY (country_key) REFERENCES dds.dim_country (country_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_country_country
    ON dds.dim_fta_country (country_key);

COMMENT ON TABLE dds.dim_fta_country IS
    'Bridge table: FTA × member country. '
    'Replaces the flat text partner_countries field in the raw image schema.';

-- ---------------------------------------------------------------------------
-- dds.fact_exchange_rate  — daily exchange rate fact
-- Grain: one row per (rate_date, base_currency, quote_currency).
-- Linked to dim_time by (year, month) of the rate_date.
-- Stores both the raw rate and the derived vnd_per_usd for convenience.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_exchange_rate (
    rate_key            BIGSERIAL    NOT NULL,   -- surrogate key

    -- Dimension FKs
    time_key            INTEGER      NOT NULL,   -- FK → dds.dim_time (YYYYMM)
    base_currency_key   INTEGER      NOT NULL,   -- FK → dds.dim_currency
    quote_currency_key  INTEGER      NOT NULL,   -- FK → dds.dim_currency

    -- Grain
    rate_date           DATE         NOT NULL,   -- exact calendar date of the rate

    -- Measures
    rate_raw            NUMERIC(18,10) NOT NULL, -- raw rate from source (e.g. VND per 1 USD)
    exchange_rate       NUMERIC(18,6)  NOT NULL, -- vnd_per_usd = 1 / rate_raw

    -- Lineage
    source_system       VARCHAR(50)  NOT NULL DEFAULT 'FRANKFURTER',
    batch_id            UUID,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

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
COMMENT ON COLUMN dds.fact_exchange_rate.rate_raw       IS 'Raw rate from Frankfurter API (e.g. base=VND → USD value of 1 VND).';
COMMENT ON COLUMN dds.fact_exchange_rate.exchange_rate  IS 'Derived vnd_per_usd = 1 / rate_raw. Used for trade value conversion.';

-- ---------------------------------------------------------------------------
-- dds.fact_trade_transaction  — central star fact table
-- Grain: time × product × partner_country × flow_type × source_system.
-- value_vnd is pre-computed at load time using the month-end exchange rate.
-- fta_keys stores an array of dim_fta surrogate keys for FTA utilization.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_trade_transaction (
    trade_key       BIGSERIAL    NOT NULL,   -- surrogate key

    -- Dimension FKs
    time_key        INTEGER      NOT NULL,   -- FK → dds.dim_time
    product_key     BIGINT       NOT NULL,   -- FK → dds.dim_product (is_current at load time)
    partner_key     BIGINT       NOT NULL,   -- FK → dds.dim_country (is_current at load time)

    -- FTA utilization (denormalized array of dim_fta surrogate keys, is_current at load time)
    fta_keys        INTEGER[],              -- NULL if no FTA utilization recorded

    -- Degenerate dimensions / grain attributes
    flow_type       BOOLEAN      NOT NULL,  -- TRUE = Export, FALSE = Import
    source_system   VARCHAR(20)  NOT NULL,  -- UN_COMTRADE, NSO, TRADE_MAP

    -- Measures (USD)
    value           NUMERIC(18,6),          -- trade value in USD
    quantity        NUMERIC(18,6),
    unit            VARCHAR(20),

    -- Pre-computed VND measure (value * month-end vnd_per_usd)
    value_vnd       NUMERIC(18,2),

    -- Lineage
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_fact_trade PRIMARY KEY (trade_key),
    CONSTRAINT uq_dds_fact_trade_grain
        UNIQUE (time_key, product_key, partner_key, flow_type, source_system),
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
    'Central star fact. Grain: time × product × partner × flow_type × source_system. '
    'value_vnd pre-computed at ETL load time using month-end VND/USD rate.';
COMMENT ON COLUMN dds.fact_trade_transaction.flow_type  IS 'TRUE = Export, FALSE = Import.';
COMMENT ON COLUMN dds.fact_trade_transaction.fta_keys   IS 'Array of dim_fta.fta_key for FTAs utilised in this trade.';
COMMENT ON COLUMN dds.fact_trade_transaction.value_vnd  IS 'Pre-computed: value (USD) × month-end vnd_per_usd.';
