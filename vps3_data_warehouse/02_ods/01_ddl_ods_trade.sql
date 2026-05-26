-- =============================================================================
-- 01_ddl_ods_trade.sql — Operational Data Store (ODS) Layer DDL
-- Schema: ods
--
-- Design principles (Inmon):
--   • Typed columns — data promoted from stg after cleansing.
--   • Source-integrated: one record per source system event/snapshot.
--   • Natural business keys preserved; surrogate keys not yet introduced.
--   • batch_id and source_system provide full lineage back to stg.
--   • No star schema here — data is still largely source-normalized.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- ods.trade_flow
-- Typed, cleansed record of each bilateral trade event.
-- Deduplicated on (reporter_code, partner_code, hs_code, period_year,
-- trade_flow, source_system) — one row per source per event.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.trade_flow (
    ods_id           BIGSERIAL     NOT NULL,
    -- Business natural key components
    reporter_code    CHAR(3)       NOT NULL,  -- ISO-3
    partner_code     CHAR(3)       NOT NULL,  -- ISO-3
    hs_code          VARCHAR(10)   NOT NULL,
    period_year      SMALLINT      NOT NULL,
    trade_flow       VARCHAR(10)   NOT NULL CHECK (trade_flow IN ('Export','Import')),
    -- Measures
    trade_value_usd  NUMERIC(20,2),
    quantity         NUMERIC(20,4),
    quantity_unit    VARCHAR(20),
    -- Lineage / metadata
    source_system    VARCHAR(50)   NOT NULL,
    source_file      VARCHAR(500),
    batch_id         UUID          NOT NULL,
    is_late_arriving BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_ods_trade_flow PRIMARY KEY (ods_id),
    CONSTRAINT uq_ods_trade_flow UNIQUE (reporter_code, partner_code, hs_code,
                                         period_year, trade_flow, source_system)
);

COMMENT ON TABLE ods.trade_flow
    IS 'Integrated, typed trade flow records from all source systems (Inmon ODS layer).';
COMMENT ON COLUMN ods.trade_flow.is_late_arriving
    IS 'Set TRUE by late_arriving_handler when the record year is behind the current watermark.';

CREATE INDEX IF NOT EXISTS ix_ods_trade_flow_reporter ON ods.trade_flow (reporter_code);
CREATE INDEX IF NOT EXISTS ix_ods_trade_flow_period   ON ods.trade_flow (period_year);
CREATE INDEX IF NOT EXISTS ix_ods_trade_flow_batch    ON ods.trade_flow (batch_id);

-- ---------------------------------------------------------------------------
-- ods.country_ref
-- Consolidated country reference after merging stg sources.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.country_ref (
    ods_id       BIGSERIAL    NOT NULL,
    iso3_code    CHAR(3)      NOT NULL,
    iso2_code    CHAR(2),
    country_name VARCHAR(200) NOT NULL,
    region       VARCHAR(100),
    source_system VARCHAR(50) NOT NULL,
    batch_id     UUID         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_ods_country_ref  PRIMARY KEY (ods_id),
    CONSTRAINT uq_ods_country_iso3 UNIQUE (iso3_code, source_system)
);

-- ---------------------------------------------------------------------------
-- ods.hs_product_ref
-- Consolidated HS product reference.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.hs_product_ref (
    ods_id       BIGSERIAL    NOT NULL,
    hs_code      VARCHAR(10)  NOT NULL,
    hs_chapter   CHAR(2)      NOT NULL,
    description  VARCHAR(500) NOT NULL,
    hs_version   VARCHAR(20)  NOT NULL DEFAULT 'HS2017',
    source_system VARCHAR(50) NOT NULL,
    batch_id     UUID         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_ods_hs_product_ref  PRIMARY KEY (ods_id),
    CONSTRAINT uq_ods_hs_code_version UNIQUE (hs_code, hs_version, source_system)
);

-- ---------------------------------------------------------------------------
-- ods.etl_watermark
-- Tracks the highest period_year successfully loaded per source system.
-- Used by late_arriving_handler.py to detect out-of-order records.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.etl_watermark (
    source_system  VARCHAR(50) NOT NULL,
    max_period_year SMALLINT   NOT NULL,
    last_updated   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_ods_etl_watermark PRIMARY KEY (source_system)
);

COMMENT ON TABLE ods.etl_watermark
    IS 'High-watermark tracker per source — enables late-arriving data detection.';
