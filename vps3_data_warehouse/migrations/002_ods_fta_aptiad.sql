-- Migration 002: expand ods.fta for APTIAD reference data (SCD Type 1 on aptiad_no)
-- Safe for empty or legacy minimal ods.fta — drops and recreates the table.

DROP TABLE IF EXISTS ods.fta;

CREATE TABLE ods.fta (
    fta_id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aptiad_no                       INTEGER NOT NULL,

    -- Core agreement attributes
    fta_name                        VARCHAR(300),
    member_countries                TEXT[],
    status                          VARCHAR(80),
    scope                           VARCHAR(80),
    agreement_type                  VARCHAR(120),

    -- Upgrade tracking
    is_upgraded                     BOOLEAN,
    upgraded_status                 VARCHAR(120),
    year_signature_upgraded         INTEGER,
    year_enforcement_upgraded       INTEGER,

    -- Trade in goods
    has_trade_goods                 BOOLEAN,
    year_signature_goods            INTEGER,
    year_enforcement_goods          INTEGER,
    wto_notification_goods          TEXT,
    wto_notification_link           TEXT,
    wto_notification_year_goods     INTEGER,
    wto_consideration_goods         TEXT,

    -- Trade in services
    has_trade_services              BOOLEAN,
    year_signature_services         INTEGER,
    year_enforcement_services       INTEGER,
    wto_notification_services       TEXT,
    wto_notification_year_services  INTEGER,
    wto_consideration_services      TEXT,
    liberalization_services         TEXT,

    -- Investment
    has_investment                  BOOLEAN,
    year_signature_investment       INTEGER,
    year_enforcement_investment     INTEGER,
    liberalization_investment       TEXT,
    bit_unctad                      TEXT,

    -- Chapter provisions (wide boolean flags)
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

    -- Reference & lineage
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
