-- =============================================================================
-- 01_ddl_ods_trade.sql — Operational Data Store (ODS) Layer DDL
-- Schema: ods
--
-- Design rules for this layer (Inmon):
--   • Typed columns — data promoted from stg after cleansing.
--   • Natural business keys preserved; no surrogate keys yet.
--   • One row per source system event — deduplicated on grain key.
--   • batch_id (UUID) and source_system provide full lineage back to stage.
--
-- TODO: Finalize column types once stg schema is locked.
--       Unique constraint grain must match the ETL dedup key.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ods;

-- ============================================================================
-- ods.trade_transaction (Main table)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ods.trade_transaction (
    ods_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    year                INTEGER NOT NULL,
    quarter             SMALLINT,
    month               SMALLINT NOT NULL,
    hs_code             VARCHAR(8),
    category_chapter    TEXT,
    category_heading    TEXT,
    product_name        TEXT,
    partner_code        VARCHAR(3),
    partner_name        TEXT,
    partner_region      TEXT,
    partner_continent   TEXT,
    fta_keys            INT[],                      -- array of FTA uuids
    flow_type           BOOLEAN NOT NULL,
    value               NUMERIC(18,6),               -- USD
    quantity            NUMERIC(18,6),
    unit                VARCHAR(20),                 -- ton, kg, ...
    record_source       VARCHAR(20),                 -- UN_COMTRADE, NSO, TRADE_MAP
    
    -- Lineage & Quality
    source_system       VARCHAR(50) NOT NULL,
    batch_id            UUID NOT NULL,
    is_late_arriving    BOOLEAN DEFAULT FALSE,
    quality_flags       TEXT[],                      -- array of flags
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT uq_ods_trade_transaction 
        UNIQUE (year, month, hs_code, partner_code, flow_type, record_source)
);

-- ============================================================================
-- ods.fta
-- ============================================================================
CREATE TABLE IF NOT EXISTS ods.fta (
    fta_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fta_name            VARCHAR(200),
    enforcement_year    INTEGER,
    partner_countries   TEXT[],
    status              VARCHAR(50),
    source_system       VARCHAR(50),
    batch_id            UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Watermark for late arriving
CREATE TABLE IF NOT EXISTS ods.etl_watermark (
    source_system    VARCHAR(50) PRIMARY KEY,
    max_period_year  SMALLINT NOT NULL,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);