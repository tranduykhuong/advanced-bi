-- =============================================================================
-- 02_ddl_stage_aptiad.sql — Stage table for APTIAD FTA reference data
-- Schema: stage
--
-- Landing zone: raw TEXT values from APTIAD CSV exports (Asia-Pacific Trade
-- and Investment Agreement Database). Typed cleansing happens at ODS layer.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_aptiad (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    aptiad_no                   INTEGER NOT NULL,
    title                       TEXT,
    members_raw                 TEXT,

    -- Agreement metadata
    status                      TEXT,
    scope                       TEXT,
    agreement_type              TEXT,
    upgraded                    TEXT,
    upgraded_status             TEXT,
    year_signature_upgraded     TEXT,
    year_enforcement_upgraded   TEXT,

    -- Trade in goods
    trade_in_goods              TEXT,
    year_signature_goods        TEXT,
    year_enforcement_goods      TEXT,
    wto_notification_goods      TEXT,
    wto_notification_link_goods TEXT,
    wto_notification_year_goods TEXT,
    wto_consideration_goods     TEXT,

    -- Safeguard provisions
    sps_tbt                     TEXT,
    anti_dumping_duty           TEXT,
    safeguard                   TEXT,

    -- Trade in services
    trade_in_services           TEXT,
    year_signature_services     TEXT,
    year_enforcement_services   TEXT,
    wto_notification_services   TEXT,
    wto_notification_year_services TEXT,
    wto_consideration_services  TEXT,
    liberalization_services     TEXT,

    -- Investment
    investment                  TEXT,
    year_signature_investment   TEXT,
    year_enforcement_investment TEXT,
    liberalization_investment   TEXT,
    bit_unctad                  TEXT,

    -- Chapter provisions
    trade_facilitation          TEXT,
    gov_procurement             TEXT,
    competition_policy          TEXT,
    intellectual_property       TEXT,
    dispute_settlement          TEXT,
    movement_natural_persons    TEXT,
    sd_related                  TEXT,
    sd_by_concept               TEXT,
    labour                      TEXT,
    human_rights                TEXT,
    gender                      TEXT,
    health                      TEXT,
    environment                 TEXT,
    smes                        TEXT,
    technical_cooperation       TEXT,
    transparency                TEXT,
    financial_services          TEXT,
    telecommunications          TEXT,
    ecommerce                   TEXT,
    ecommerce_consumer_protection TEXT,
    ecommerce_personal_data     TEXT,
    ecommerce_data_flows        TEXT,

    -- Reference
    link_website                TEXT,

    -- Lineage
    source_file                 TEXT,
    snapshot_date               DATE,
    batch_id                    UUID,
    extracted_at                TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_aptiad_no ON stage.stage_aptiad (aptiad_no);
CREATE INDEX IF NOT EXISTS idx_stage_aptiad_snapshot ON stage.stage_aptiad (snapshot_date);
