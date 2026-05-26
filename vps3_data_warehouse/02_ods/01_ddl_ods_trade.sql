-- =============================================================================
-- 01_ddl_ods_trade.sql — Operational Data Store (ODS) Layer DDL
-- Schema: ods
--
-- Design rules for this layer (Inmon):
--   • Typed columns — data promoted from stg after cleansing.
--   • Natural business keys preserved; no surrogate keys yet.
--   • One row per source system event — deduplicated on grain key.
--   • batch_id (UUID) and source_system provide full lineage back to stg.
--
-- TODO: Finalize column types once stg schema is locked.
--       Unique constraint grain must match the ETL dedup key.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- ods.trade_flow
-- Typed, cleansed, deduplicated trade event record.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.trade_flow (
    ods_id           BIGSERIAL    NOT NULL,

    -- TODO: add typed business columns
    -- reporter_code    CHAR(3)      NOT NULL,
    -- partner_code     CHAR(3)      NOT NULL,
    -- hs_code          VARCHAR(10)  NOT NULL,
    -- period_year      SMALLINT     NOT NULL,
    -- trade_flow       VARCHAR(10)  NOT NULL CHECK (trade_flow IN ('Export','Import')),
    -- trade_value_usd  NUMERIC(20,2),
    -- quantity         NUMERIC(20,4),
    -- quantity_unit    VARCHAR(20),

    -- Lineage (required — do not remove)
    source_system    VARCHAR(50)  NOT NULL,
    source_file      VARCHAR(500),
    batch_id         UUID         NOT NULL,
    is_late_arriving BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_ods_trade_flow PRIMARY KEY (ods_id)

    -- TODO: add unique constraint matching the dedup grain, e.g.:
    -- CONSTRAINT uq_ods_trade_flow UNIQUE (reporter_code, partner_code, hs_code,
    --                                      period_year, trade_flow, source_system)
);

-- ---------------------------------------------------------------------------
-- ods.country_ref
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.country_ref (
    ods_id        BIGSERIAL    NOT NULL,

    -- TODO: add typed reference columns
    -- iso3_code     CHAR(3)      NOT NULL,
    -- iso2_code     CHAR(2),
    -- country_name  VARCHAR(200) NOT NULL,
    -- region        VARCHAR(100),

    source_system VARCHAR(50)  NOT NULL,
    batch_id      UUID         NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_ods_country_ref PRIMARY KEY (ods_id)

    -- TODO: CONSTRAINT uq_ods_country_iso3 UNIQUE (iso3_code, source_system)
);

-- ---------------------------------------------------------------------------
-- ods.hs_product_ref
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.hs_product_ref (
    ods_id        BIGSERIAL    NOT NULL,

    -- TODO: add typed reference columns
    -- hs_code       VARCHAR(10)  NOT NULL,
    -- hs_chapter    CHAR(2)      NOT NULL,
    -- description   VARCHAR(500) NOT NULL,
    -- hs_version    VARCHAR(20)  NOT NULL DEFAULT 'HS2017',

    source_system VARCHAR(50)  NOT NULL,
    batch_id      UUID         NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_ods_hs_product_ref PRIMARY KEY (ods_id)

    -- TODO: CONSTRAINT uq_ods_hs_code_version UNIQUE (hs_code, hs_version, source_system)
);

-- ---------------------------------------------------------------------------
-- ods.etl_watermark
-- Tracks the highest period_year successfully processed per source system.
-- Used by late_arriving_handler.py to detect out-of-order records.
-- Do NOT remove — referenced by ETL pipeline.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ods.etl_watermark (
    source_system    VARCHAR(50) NOT NULL,
    max_period_year  SMALLINT    NOT NULL,
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_ods_etl_watermark PRIMARY KEY (source_system)
);
