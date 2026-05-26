-- =============================================================================
-- 01_ddl_dds_star.sql — Dimensional Data Store (DDS) — Star Schema DDL
-- Schema: dds
--
-- Design principles (Kimball):
--   • Surrogate keys (integer sequences) on all dimension tables.
--   • SCD Type 2 on dds.dim_country (valid_from / valid_to / is_current).
--   • SCD Type 1 on dds.dim_product  (overwrite — no history kept).
--   • dds.dim_date is a fully pre-populated calendar table.
--   • fact_trade uses INTEGER surrogate FK references for fast joins.
--   • One row per grain: reporter × partner × product × date_year × flow.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- dds.dim_date
-- Conformed calendar dimension — populated by ETL or a separate seed script.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_date (
    date_sk       INTEGER      NOT NULL,   -- YYYYMMDD integer key
    full_date     DATE         NOT NULL,
    year          SMALLINT     NOT NULL,
    quarter       SMALLINT     NOT NULL,
    month         SMALLINT     NOT NULL,
    month_name    VARCHAR(10)  NOT NULL,
    week_of_year  SMALLINT     NOT NULL,
    day_of_month  SMALLINT     NOT NULL,
    day_of_week   SMALLINT     NOT NULL,
    day_name      VARCHAR(10)  NOT NULL,
    is_weekend    BOOLEAN      NOT NULL,
    CONSTRAINT pk_dds_dim_date PRIMARY KEY (date_sk)
);

COMMENT ON TABLE dds.dim_date
    IS 'Conformed calendar dimension. Populate via seed script: generate_dim_date.sql.';

-- Seed rows for the analytical years 2018–2030 (year-grain only — fill months/days as needed)
INSERT INTO dds.dim_date (date_sk, full_date, year, quarter, month, month_name, week_of_year, day_of_month, day_of_week, day_name, is_weekend)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER,
    d,
    EXTRACT(YEAR    FROM d)::SMALLINT,
    EXTRACT(QUARTER FROM d)::SMALLINT,
    EXTRACT(MONTH   FROM d)::SMALLINT,
    TO_CHAR(d, 'Month'),
    EXTRACT(WEEK    FROM d)::SMALLINT,
    EXTRACT(DAY     FROM d)::SMALLINT,
    EXTRACT(DOW     FROM d)::SMALLINT,
    TO_CHAR(d, 'Day'),
    EXTRACT(DOW FROM d) IN (0,6)
FROM generate_series('2018-01-01'::DATE, '2030-12-31'::DATE, '1 day'::INTERVAL) AS d
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- dds.dim_country  — SCD Type 2
-- Tracks historical changes to country names and regions over time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_country (
    country_sk    SERIAL       NOT NULL,   -- surrogate key
    country_bk    CHAR(3)      NOT NULL,   -- business key (ISO-3)
    country_name  VARCHAR(200) NOT NULL,
    region        VARCHAR(100),
    -- SCD2 validity columns
    valid_from    DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to      DATE         NOT NULL DEFAULT '9999-12-31',
    is_current    BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Lineage
    batch_id      UUID,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_dds_dim_country  PRIMARY KEY (country_sk),
    -- Partial unique: only one current row per business key
    CONSTRAINT uq_dds_country_current UNIQUE (country_bk, is_current)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE dds.dim_country
    IS 'SCD Type 2 country dimension — valid_from/valid_to track name/region changes over time.';
COMMENT ON COLUMN dds.dim_country.is_current
    IS 'TRUE for the active version; FALSE for expired historical rows.';

CREATE INDEX IF NOT EXISTS ix_dds_country_bk      ON dds.dim_country (country_bk);
CREATE INDEX IF NOT EXISTS ix_dds_country_current ON dds.dim_country (country_bk) WHERE is_current;

-- ---------------------------------------------------------------------------
-- dds.dim_product  — SCD Type 1
-- HS description updates overwrite in-place (no history kept).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.dim_product (
    product_sk    SERIAL       NOT NULL,   -- surrogate key
    product_bk    VARCHAR(10)  NOT NULL,   -- business key (hs_code)
    hs_chapter    CHAR(2)      NOT NULL,
    description   VARCHAR(500) NOT NULL,
    hs_version    VARCHAR(20)  NOT NULL DEFAULT 'HS2017',
    -- SCD1: last_updated replaces valid_from/to (no history)
    batch_id      UUID,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_dds_dim_product  PRIMARY KEY (product_sk),
    CONSTRAINT uq_dds_product_bk   UNIQUE (product_bk, hs_version)
);

COMMENT ON TABLE dds.dim_product
    IS 'SCD Type 1 product dimension — description updates overwrite; no version history retained.';

-- ---------------------------------------------------------------------------
-- dds.fact_trade
-- Central star fact table. All dimension references use surrogate keys.
-- Grain: one row per (reporter × partner × product × year × trade_flow).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dds.fact_trade (
    fact_sk           BIGSERIAL    NOT NULL,
    -- Dimension surrogate keys
    reporter_sk       INTEGER      NOT NULL,
    partner_sk        INTEGER      NOT NULL,
    product_sk        INTEGER      NOT NULL,
    date_year_sk      INTEGER      NOT NULL,   -- references dim_date.date_sk for Jan 1 of year
    -- Degenerate dimension
    trade_flow        VARCHAR(10)  NOT NULL CHECK (trade_flow IN ('Export','Import')),
    -- Measures (additive)
    trade_value_usd   NUMERIC(20,2),
    quantity          NUMERIC(20,4),
    quantity_unit     VARCHAR(20),
    -- Lineage
    source_system     VARCHAR(50)  NOT NULL,
    batch_id          UUID,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_dds_fact_trade PRIMARY KEY (fact_sk),
    CONSTRAINT uq_dds_fact_grain UNIQUE (reporter_sk, partner_sk, product_sk,
                                          date_year_sk, trade_flow, source_system),
    CONSTRAINT fk_dds_fact_reporter  FOREIGN KEY (reporter_sk)  REFERENCES dds.dim_country (country_sk),
    CONSTRAINT fk_dds_fact_partner   FOREIGN KEY (partner_sk)   REFERENCES dds.dim_country (country_sk),
    CONSTRAINT fk_dds_fact_product   FOREIGN KEY (product_sk)   REFERENCES dds.dim_product (product_sk),
    CONSTRAINT fk_dds_fact_date      FOREIGN KEY (date_year_sk) REFERENCES dds.dim_date    (date_sk)
);

COMMENT ON TABLE dds.fact_trade
    IS 'Central trade fact table (Kimball star). Grain: reporter × partner × product × year × flow.';

CREATE INDEX IF NOT EXISTS ix_dds_fact_reporter  ON dds.fact_trade (reporter_sk);
CREATE INDEX IF NOT EXISTS ix_dds_fact_partner   ON dds.fact_trade (partner_sk);
CREATE INDEX IF NOT EXISTS ix_dds_fact_product   ON dds.fact_trade (product_sk);
CREATE INDEX IF NOT EXISTS ix_dds_fact_year      ON dds.fact_trade (date_year_sk);
