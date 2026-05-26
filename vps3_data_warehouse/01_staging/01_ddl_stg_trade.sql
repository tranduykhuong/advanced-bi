-- =============================================================================
-- 01_ddl_stg_trade.sql — Staging Layer DDL
-- Schema: stg
--
-- Design rules for this layer:
--   • ALL columns must be VARCHAR — avoids type-mismatch rejections on raw load.
--   • No foreign keys — incoming data may be dirty.
--   • Tables are TRUNCATED at the start of each ETL run (idempotent reload).
--   • Every table must include: source_system, batch_id, loaded_at for lineage.
--
-- TODO: Define one table per source feed.
--       Suggested starting points are commented below.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- stg.trade_flow_raw
-- Landing table for TradeMap API + UN Comtrade CSV records.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.trade_flow_raw (
    stg_id          BIGSERIAL    NOT NULL,

    -- TODO: add source columns as VARCHAR
    -- reporter_code   VARCHAR,
    -- reporter_name   VARCHAR,
    -- partner_code    VARCHAR,
    -- partner_name    VARCHAR,
    -- hs_code         VARCHAR,
    -- hs_description  VARCHAR,
    -- period_year     VARCHAR,
    -- period_type     VARCHAR,
    -- trade_flow      VARCHAR,
    -- trade_value_usd VARCHAR,
    -- quantity        VARCHAR,
    -- quantity_unit   VARCHAR,

    -- Lineage (required — do not remove)
    source_system   VARCHAR(50)  NOT NULL,
    source_file     VARCHAR(500),
    batch_id        VARCHAR(36),
    loaded_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_stg_trade_flow_raw PRIMARY KEY (stg_id)
);

-- ---------------------------------------------------------------------------
-- stg.gso_trade_raw
-- Landing table for GSO (Vietnam General Statistics Office) CSV exports.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.gso_trade_raw (
    stg_id          BIGSERIAL    NOT NULL,

    -- TODO: add GSO-specific source columns as VARCHAR
    -- report_year     VARCHAR,
    -- reporter_code   VARCHAR,
    -- partner_code    VARCHAR,
    -- hs_code         VARCHAR,
    -- trade_flow      VARCHAR,
    -- trade_value_vnd VARCHAR,
    -- trade_value_usd VARCHAR,
    -- quantity        VARCHAR,
    -- quantity_unit   VARCHAR,

    -- Lineage (required — do not remove)
    source_system   VARCHAR(50)  NOT NULL DEFAULT 'GSO_CSV',
    source_file     VARCHAR(500),
    batch_id        VARCHAR(36),
    loaded_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_stg_gso_trade_raw PRIMARY KEY (stg_id)
);

-- ---------------------------------------------------------------------------
-- stg.country_ref_raw  — dimension staging for country reference data
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.country_ref_raw (
    stg_id        BIGSERIAL   NOT NULL,

    -- TODO: add reference columns as VARCHAR
    -- iso3_code     VARCHAR,
    -- iso2_code     VARCHAR,
    -- country_name  VARCHAR,
    -- region        VARCHAR,

    source_system VARCHAR(50),
    batch_id      VARCHAR(36),
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_stg_country_ref_raw PRIMARY KEY (stg_id)
);

-- ---------------------------------------------------------------------------
-- stg.hs_product_ref_raw  — dimension staging for HS commodity codes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.hs_product_ref_raw (
    stg_id        BIGSERIAL   NOT NULL,

    -- TODO: add reference columns as VARCHAR
    -- hs_code       VARCHAR,
    -- hs_chapter    VARCHAR,
    -- description   VARCHAR,
    -- hs_version    VARCHAR,

    source_system VARCHAR(50),
    batch_id      VARCHAR(36),
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_stg_hs_product_ref_raw PRIMARY KEY (stg_id)
);
