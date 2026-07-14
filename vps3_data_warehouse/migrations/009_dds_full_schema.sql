-- =============================================================================
-- Migration 009: DDS Full Schema
-- Applies the complete Dimensional Data Store (DDS) star schema to the database.
--
-- Execution order respects FK dependencies:
--   dim_time → dim_currency → dim_country → dim_product → dim_fta
--   → dim_fta_country (bridge)
--   → fact_exchange_rate → fact_trade_transaction
--
-- Also bundles two closely related ETL-audit additions from the same change:
--   • dim_product / dim_fta used SCD Type 2 (is_current + version + partial unique index), matching dim_country's existing pattern.
--     Per the report design, SCD2 here tracks only is_current/version — no
--     valid_from/valid_to date range (dim_country never had one either as of
--     this revision).
--   • public.etl_batch_log / public.reject_records: rejected/upserted counters
--     and a reject-records audit table shared by Stage→ODS, ODS→NDS, NDS→DDS.
--
-- All statements use IF NOT EXISTS / ON CONFLICT so this script is idempotent.
-- Safe to re-run on an existing database.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. public.etl_batch_log / public.reject_records
-- ---------------------------------------------------------------------------
ALTER TABLE public.etl_batch_log
    ADD COLUMN IF NOT EXISTS rows_rejected INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rows_upserted INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.reject_records (
    reject_id        BIGSERIAL    NOT NULL,
    batch_id         UUID         NOT NULL,
    process_type     SMALLINT     NOT NULL
                                  CHECK (process_type IN (1, 2, 3)),
                                  -- 1 = Stage -> ODS, 2 = ODS -> NDS, 3 = NDS -> DDS
    source_table     VARCHAR(100) NOT NULL,
    reject_reason    TEXT         NOT NULL,
    row_data         JSONB,
    rejected_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_reject_records PRIMARY KEY (reject_id),
    CONSTRAINT fk_reject_records_batch
        FOREIGN KEY (batch_id) REFERENCES public.etl_batch_log (batch_id)
);

CREATE INDEX IF NOT EXISTS ix_reject_records_batch_id
    ON public.reject_records (batch_id);

CREATE INDEX IF NOT EXISTS ix_reject_records_process_type
    ON public.reject_records (process_type);

COMMENT ON TABLE public.reject_records IS
    'Rows rejected/excluded during ETL (Stage->ODS=1, ODS->NDS=2, NDS->DDS=3). '
    'Used for audit and data traceability alongside etl_batch_log.';

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
    batch_id        UUID,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_country PRIMARY KEY (country_key)
);

-- Retrofit: earlier revisions of this migration added valid_from/valid_to.
-- Per the report design, SCD2 here only needs is_current + version.
ALTER TABLE dds.dim_country
    DROP COLUMN IF EXISTS valid_from,
    DROP COLUMN IF EXISTS valid_to;

CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_country_current
    ON dds.dim_country (country_code)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_country_code
    ON dds.dim_country (country_code);

COMMENT ON TABLE  dds.dim_country IS 'SCD Type 2 country dimension. One is_current=TRUE row per country_code.';
COMMENT ON COLUMN dds.dim_country.version    IS 'Increments with each SCD2 change.';

-- ---------------------------------------------------------------------------
-- 4. dds.dim_product  (SCD Type 2)
-- Originally shipped as SCD1 (uq_dds_dim_product_bk); the ALTER/DROP/CREATE
-- block below retrofits an existing SCD1 table to SCD2 in place.
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

    CONSTRAINT pk_dds_dim_product    PRIMARY KEY (product_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_chapter
    ON dds.dim_product (hs_chapter);

ALTER TABLE dds.dim_product ADD COLUMN IF NOT EXISTS hs_heading CHAR(4);

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_heading
    ON dds.dim_product (hs_heading);

-- SCD2 retrofit: swap the plain business-key unique constraint for a partial
-- unique index scoped to is_current = TRUE. Drop valid_from/valid_to if an
-- earlier revision of this migration already added them — per the report
-- design, SCD2 here only needs is_current + version.
ALTER TABLE dds.dim_product
    DROP COLUMN IF EXISTS valid_from,
    DROP COLUMN IF EXISTS valid_to;

ALTER TABLE dds.dim_product DROP CONSTRAINT IF EXISTS uq_dds_dim_product_bk;

CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_product_current
    ON dds.dim_product (hs_code, hs_version)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_product_bk
    ON dds.dim_product (hs_code, hs_version);

COMMENT ON TABLE  dds.dim_product IS 'SCD Type 2 product dimension. One is_current=TRUE row per (hs_code, hs_version).';
COMMENT ON COLUMN dds.dim_product.version    IS 'Increments with each SCD2 change.';

-- ---------------------------------------------------------------------------
-- 5. dds.dim_fta  (SCD Type 2)
-- Originally shipped as SCD1 (uq_dds_dim_fta_bk); the ALTER/DROP/CREATE
-- block below retrofits an existing SCD1 table to SCD2 in place.
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

    CONSTRAINT pk_dds_dim_fta    PRIMARY KEY (fta_key)
);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_status
    ON dds.dim_fta (status);

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_enforcement_year
    ON dds.dim_fta (enforcement_year);

-- SCD2 retrofit: swap the plain business-key unique constraint for a partial
-- unique index scoped to is_current = TRUE. Drop valid_from/valid_to if an
-- earlier revision of this migration already added them — per the report
-- design, SCD2 here only needs is_current + version.
ALTER TABLE dds.dim_fta
    DROP COLUMN IF EXISTS valid_from,
    DROP COLUMN IF EXISTS valid_to;

ALTER TABLE dds.dim_fta DROP CONSTRAINT IF EXISTS uq_dds_dim_fta_bk;

CREATE UNIQUE INDEX IF NOT EXISTS uix_dds_dim_fta_current
    ON dds.dim_fta (fta_bk)
    WHERE is_current = TRUE;

CREATE INDEX IF NOT EXISTS ix_dds_dim_fta_bk
    ON dds.dim_fta (fta_bk);

COMMENT ON TABLE  dds.dim_fta IS 'SCD Type 2 Free Trade Agreement dimension. One is_current=TRUE row per fta_bk.';
COMMENT ON COLUMN dds.dim_fta.fta_bk      IS 'Business key — references nds.fta.fta_id.';
COMMENT ON COLUMN dds.dim_fta.version     IS 'Increments with each SCD2 change.';

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
    source_system   VARCHAR(20)  NOT NULL,
    value           NUMERIC(18,6),
    quantity        NUMERIC(18,6),
    unit            VARCHAR(20),
    value_vnd       NUMERIC(18,2),
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
COMMENT ON COLUMN dds.fact_trade_transaction.flow_type IS 'TRUE = Export, FALSE = Import.';
COMMENT ON COLUMN dds.fact_trade_transaction.fta_keys  IS 'Array of dim_fta.fta_key for FTAs utilised in this trade.';
COMMENT ON COLUMN dds.fact_trade_transaction.value_vnd IS 'Pre-computed: value (USD) × month-end vnd_per_usd.';
