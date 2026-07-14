-- =============================================================================
-- 01_ddl_ods_trade.sql — Operational Data Store (ODS) Layer DDL
-- Schema: ods
--
-- Design rules for this layer (Inmon):
--   • Typed columns — data promoted from stg after cleansing.
--   • Natural business keys preserved; no surrogate keys yet.
--   • One row per source system event — deduplicated on grain key.
--   • batch_id (UUID) provides full lineage back to stage.
--   • source_system identifies the data provider (UN_COMTRADE / NSO / TRADE_MAP
--     for trade_transaction; APTIAD / FRANKFURTER for fta / exchange_rate).
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
    chapter_name    TEXT,
    heading_name    TEXT,
    product_name        TEXT,
    partner_code        VARCHAR(3),
    partner_name        TEXT,
    partner_region      TEXT,
    partner_continent   TEXT,
    flow_type           BOOLEAN NOT NULL,
    value               NUMERIC(18,6),               -- USD
    quantity            NUMERIC(18,6),
    unit                VARCHAR(20),                 -- ton, kg, ...
    source_system       VARCHAR(20) NOT NULL,        -- UN_COMTRADE, NSO, TRADE_MAP

    -- Lineage & Quality
    batch_id            UUID NOT NULL,
    is_late_arriving    BOOLEAN DEFAULT FALSE,
    quality_flags       TEXT[],                      -- array of flags
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_trade_transaction
        UNIQUE (year, month, hs_code, partner_code, flow_type, source_system)
);

-- ============================================================================
-- ods.fta (APTIAD reference data — SCD Type 1 on aptiad_no)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ods.fta (
    fta_id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aptiad_no                       INTEGER NOT NULL,

    fta_name                        VARCHAR(300),
    member_countries                TEXT[],
    status                          VARCHAR(80),
    scope                           VARCHAR(80),
    agreement_type                  VARCHAR(120),

    is_upgraded                     BOOLEAN,
    upgraded_status                 VARCHAR(120),
    year_signature_upgraded         INTEGER,
    year_enforcement_upgraded       INTEGER,

    has_trade_goods                 BOOLEAN,
    year_signature_goods            INTEGER,
    year_enforcement_goods          INTEGER,
    wto_notification_goods          TEXT,
    wto_notification_link           TEXT,
    wto_notification_year_goods     INTEGER,
    wto_consideration_goods         TEXT,

    has_trade_services              BOOLEAN,
    year_signature_services         INTEGER,
    year_enforcement_services       INTEGER,
    wto_notification_services       TEXT,
    wto_notification_year_services  INTEGER,
    wto_consideration_services      TEXT,
    liberalization_services         TEXT,

    has_investment                  BOOLEAN,
    year_signature_investment       INTEGER,
    year_enforcement_investment     INTEGER,
    liberalization_investment       TEXT,
    bit_unctad                      TEXT,

    provision_sps_tbt               BOOLEAN,
    provision_anti_dumping          BOOLEAN,
    provision_safeguard             BOOLEAN,
    provision_trade_facilitation    BOOLEAN,
    provision_gov_procurement       BOOLEAN,
    provision_competition_policy    BOOLEAN,
    provision_intellectual_property BOOLEAN,
    provision_dispute_settlement    BOOLEAN,
    provision_movement_natural_persons BOOLEAN,
    provision_sd_related            BOOLEAN,
    provision_sd_by_concept         BOOLEAN,
    provision_labour                BOOLEAN,
    provision_human_rights          BOOLEAN,
    provision_gender                BOOLEAN,
    provision_health                BOOLEAN,
    provision_environment           BOOLEAN,
    provision_smes                  BOOLEAN,
    provision_technical_cooperation BOOLEAN,
    provision_transparency          BOOLEAN,
    provision_financial_services    BOOLEAN,
    provision_telecommunications    BOOLEAN,
    provision_ecommerce             BOOLEAN,
    provision_ecommerce_consumer_protection BOOLEAN,
    provision_ecommerce_personal_data BOOLEAN,
    provision_ecommerce_data_flows  BOOLEAN,

    source_link                     TEXT,
    source_system                   VARCHAR(50) NOT NULL DEFAULT 'APTIAD',
    snapshot_date                   DATE,
    batch_id                        UUID,
    created_at                      TIMESTAMPTZ DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_fta_aptiad_no UNIQUE (aptiad_no)
);

CREATE INDEX IF NOT EXISTS idx_ods_fta_status ON ods.fta (status);
CREATE INDEX IF NOT EXISTS idx_ods_fta_member_countries ON ods.fta USING GIN (member_countries);

-- Watermark for late-arriving detection.
-- max_period_year/max_period_month track the latest (year, month) period
-- already loaded per source_system (e.g. TRADE_MAP, NSO, UN_COMTRADE, FRANKFURTER).
-- An incoming row whose (year, month) is older than the current watermark for
-- its source is flagged is_late_arriving = TRUE in ods.trade_transaction.
CREATE TABLE IF NOT EXISTS ods.etl_watermark (
    source_system    VARCHAR(50) PRIMARY KEY,
    max_period_year  SMALLINT NOT NULL,
    max_period_month SMALLINT,
    last_updated     TIMESTAMPTZ DEFAULT NOW()
);