-- =============================================================================
-- 01_ddl_dds_star.sql — Dimensional Data Store (DDS) Star Schema DDL
-- Schema: dds
--
-- Design rules for this layer (Kimball):
--   • Surrogate keys (integer sequences) on all dimension tables.
--   • SCD Type 2 on dds.dim_country  (valid_from / valid_to / is_current).
--   • SCD Type 1 on dds.dim_product  (overwrite — no version history kept).
--   • dds.dim_date is a conformed calendar dimension (populate via seed script).
--   • dds.fact_trade grain: reporter × partner × product × year × trade_flow.
--
-- TODO: Uncomment columns once NDS schema is finalized.
--       Ensure dim_date is populated for all report years before fact load.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- dds.dim_date  — conformed calendar dimension
-- Populate with generate_series or a separate seed script.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_date (
    date_sk       INTEGER      NOT NULL,   -- surrogate key: YYYYMMDD

    -- TODO: add calendar attributes
    -- full_date     DATE         NOT NULL,
    -- year          SMALLINT     NOT NULL,
    -- quarter       SMALLINT     NOT NULL,
    -- month         SMALLINT     NOT NULL,
    -- month_name    VARCHAR(10)  NOT NULL,
    -- week_of_year  SMALLINT     NOT NULL,
    -- day_of_month  SMALLINT     NOT NULL,
    -- day_of_week   SMALLINT     NOT NULL,
    -- day_name      VARCHAR(10)  NOT NULL,
    -- is_weekend    BOOLEAN      NOT NULL,

    CONSTRAINT pk_dds_dim_date PRIMARY KEY (date_sk)
);

-- ---------------------------------------------------------------------------
-- dds.dim_country  — SCD Type 2
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_country (
    country_sk    SERIAL       NOT NULL,   -- surrogate key

    -- TODO: add business key + attributes
    -- country_bk    CHAR(3)      NOT NULL,   -- business key (ISO-3)
    -- country_name  VARCHAR(200) NOT NULL,
    -- region        VARCHAR(100),

    -- SCD2 validity columns (required — do not remove)
    valid_from    DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to      DATE         NOT NULL DEFAULT '9999-12-31',
    is_current    BOOLEAN      NOT NULL DEFAULT TRUE,

    batch_id      UUID,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_country PRIMARY KEY (country_sk)

    -- TODO: partial unique on active row:
    -- CONSTRAINT uq_dds_country_current UNIQUE (country_bk, is_current)
    --     DEFERRABLE INITIALLY DEFERRED
);

-- ---------------------------------------------------------------------------
-- dds.dim_product  — SCD Type 1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_product (
    product_sk    SERIAL       NOT NULL,   -- surrogate key

    -- TODO: add business key + attributes
    -- product_bk    VARCHAR(10)  NOT NULL,   -- business key (hs_code)
    -- hs_chapter    CHAR(2)      NOT NULL,
    -- description   VARCHAR(500) NOT NULL,
    -- hs_version    VARCHAR(20)  NOT NULL DEFAULT 'HS2017',

    batch_id      UUID,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_dim_product PRIMARY KEY (product_sk)

    -- TODO: CONSTRAINT uq_dds_product_bk UNIQUE (product_bk, hs_version)
);

-- ---------------------------------------------------------------------------
-- dds.fact_trade  — central star fact table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_trade (
    fact_sk           BIGSERIAL    NOT NULL,

    -- TODO: add dimension surrogate key FKs + measures
    -- reporter_sk       INTEGER      NOT NULL,  -- FK → dds.dim_country
    -- partner_sk        INTEGER      NOT NULL,  -- FK → dds.dim_country
    -- product_sk        INTEGER      NOT NULL,  -- FK → dds.dim_product
    -- date_year_sk      INTEGER      NOT NULL,  -- FK → dds.dim_date (Jan 1 of year)
    -- trade_flow        VARCHAR(10)  NOT NULL CHECK (trade_flow IN ('Export','Import')),
    -- trade_value_usd   NUMERIC(20,2),
    -- quantity          NUMERIC(20,4),
    -- quantity_unit     VARCHAR(20),

    -- Lineage (required — do not remove)
    source_system     VARCHAR(50)  NOT NULL,
    batch_id          UUID,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_dds_fact_trade PRIMARY KEY (fact_sk)

    -- TODO: add grain uniqueness + FK constraints, e.g.:
    -- CONSTRAINT uq_dds_fact_grain   UNIQUE (reporter_sk, partner_sk, product_sk,
    --                                         date_year_sk, trade_flow, source_system),
    -- CONSTRAINT fk_dds_fact_reporter FOREIGN KEY (reporter_sk) REFERENCES dds.dim_country,
    -- CONSTRAINT fk_dds_fact_partner  FOREIGN KEY (partner_sk)  REFERENCES dds.dim_country,
    -- CONSTRAINT fk_dds_fact_product  FOREIGN KEY (product_sk)  REFERENCES dds.dim_product,
    -- CONSTRAINT fk_dds_fact_date     FOREIGN KEY (date_year_sk) REFERENCES dds.dim_date
);
