-- =============================================================================
-- 01_ddl_stg_trade.sql — Staging Layer DDL
-- Schema: stg
--
-- Design principles:
--   • ALL columns are VARCHAR to avoid type-mismatch rejections on load.
--   • No foreign keys — raw data may be dirty.
--   • Tables are truncated at the start of each ETL run (idempotent).
--   • loaded_at and source_system columns are mandatory for lineage.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- stg.trade_flow_raw
-- Receives records from both the TradeMap mock API and UN Comtrade CSV files.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.trade_flow_raw (
    stg_id           BIGSERIAL    NOT NULL,
    -- Source fields (raw, all VARCHAR)
    reporter_code    VARCHAR(10),
    reporter_name    VARCHAR(200),
    partner_code     VARCHAR(10),
    partner_name     VARCHAR(200),
    hs_code          VARCHAR(20),
    hs_description   VARCHAR(500),
    period_year      VARCHAR(10),
    period_type      VARCHAR(20),    -- 'Annual', 'Monthly', etc.
    trade_flow       VARCHAR(20),    -- 'Export', 'Import'
    trade_value_usd  VARCHAR(30),    -- string to handle NULL, commas, etc.
    quantity         VARCHAR(30),
    quantity_unit    VARCHAR(50),
    -- Lineage
    source_system    VARCHAR(50)  NOT NULL,  -- 'TRADEMAP_API', 'UN_COMTRADE_CSV', 'GSO_CSV'
    source_file      VARCHAR(500),           -- filename or API endpoint path
    batch_id         VARCHAR(36),            -- UUID string from etl_batch_log
    loaded_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_stg_trade_flow_raw PRIMARY KEY (stg_id)
);

COMMENT ON TABLE stg.trade_flow_raw
    IS 'Landing table for all trade flow data — truncated and reloaded each ETL cycle.';

-- ---------------------------------------------------------------------------
-- stg.gso_trade_raw
-- Receives records sourced specifically from GSO (Vietnam General Statistics
-- Office) CSV exports which carry additional local metadata.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.gso_trade_raw (
    stg_id            BIGSERIAL    NOT NULL,
    source_system     VARCHAR(50)  NOT NULL DEFAULT 'GSO_CSV',
    report_year       VARCHAR(10),
    period_type       VARCHAR(20),
    reporter_code     VARCHAR(10),
    reporter_name     VARCHAR(200),
    partner_code      VARCHAR(10),
    partner_name      VARCHAR(200),
    hs_code           VARCHAR(20),
    hs_description    VARCHAR(500),
    trade_flow        VARCHAR(20),
    trade_value_vnd   VARCHAR(30),  -- billions VND
    trade_value_usd   VARCHAR(30),  -- millions USD
    quantity          VARCHAR(30),
    quantity_unit     VARCHAR(50),
    data_quality_flag VARCHAR(20),
    source_file       VARCHAR(500),
    batch_id          VARCHAR(36),
    loaded_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_stg_gso_trade_raw PRIMARY KEY (stg_id)
);

COMMENT ON TABLE stg.gso_trade_raw
    IS 'Landing table for GSO (Vietnam) trade data — separate from UN Comtrade to preserve source schema.';

-- ---------------------------------------------------------------------------
-- stg.country_ref_raw
-- Lookup / dimension staging for country reference data.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.country_ref_raw (
    stg_id        BIGSERIAL   NOT NULL,
    iso3_code     VARCHAR(10),
    iso2_code     VARCHAR(10),
    country_name  VARCHAR(200),
    region        VARCHAR(100),
    source_system VARCHAR(50),
    batch_id      VARCHAR(36),
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_stg_country_ref_raw PRIMARY KEY (stg_id)
);

-- ---------------------------------------------------------------------------
-- stg.hs_product_ref_raw
-- Lookup / dimension staging for HS commodity codes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.hs_product_ref_raw (
    stg_id        BIGSERIAL   NOT NULL,
    hs_code       VARCHAR(20),
    hs_chapter    VARCHAR(10),
    description   VARCHAR(500),
    hs_version    VARCHAR(20),
    source_system VARCHAR(50),
    batch_id      VARCHAR(36),
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_stg_hs_product_ref_raw PRIMARY KEY (stg_id)
);
