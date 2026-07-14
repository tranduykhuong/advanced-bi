-- =============================================================================
-- 01_ddl_nds_trade.sql — Normalized Data Store (NDS) Layer DDL
-- Schema: nds
--
-- Design rules for this layer:
--   • Fully normalized to Third Normal Form (3NF).
--   • Enforces referential integrity via FOREIGN KEY constraints.
--   • Natural business keys are the primary identifiers.
--   • This is the Inmon integration point before Kimball denormalization.
--
-- Source: ods.trade_transaction, ods.fta
-- Provision flags remain in ods.fta — query ODS directly when needed.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS nds;

-- ---------------------------------------------------------------------------
-- nds.country
-- Master country/territory reference (3NF, authoritative ISO-3 codes).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.country (
    country_code    VARCHAR(3)   NOT NULL,
    country_name    VARCHAR(200),
    continent       VARCHAR(100),
    region          VARCHAR(100),

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_country PRIMARY KEY (country_code)
);

-- ---------------------------------------------------------------------------
-- nds.product
-- Master HS commodity code reference.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.product (
    hs_code           VARCHAR(8)   NOT NULL,
    hs_version        VARCHAR(10)  NOT NULL DEFAULT 'HS2017',
    chapter_name  TEXT,
    heading_name  TEXT,
    product_name      TEXT,

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_product PRIMARY KEY (hs_code, hs_version)
);

-- ---------------------------------------------------------------------------
-- nds.time
-- Month-level time dimension (trade data grain).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.time (
    time_id    UUID         NOT NULL DEFAULT gen_random_uuid(),
    year       SMALLINT     NOT NULL,
    quarter    SMALLINT,
    month      SMALLINT     NOT NULL,

    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_time PRIMARY KEY (time_id),
    CONSTRAINT uq_nds_time_year_month UNIQUE (year, month),
    CONSTRAINT chk_nds_time_month CHECK (month BETWEEN 1 AND 12)
);

-- ---------------------------------------------------------------------------
-- nds.fta
-- Free Trade Agreement reference (core attributes only).
-- Provision detail stays in ods.fta — join via fta_id when needed.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.fta (
    fta_id            UUID         NOT NULL,
    aptiad_no         INTEGER      NOT NULL,
    fta_name          VARCHAR(300),
    status            VARCHAR(80),
    scope             VARCHAR(80),
    agreement_type    VARCHAR(120),
    enforcement_year  INTEGER,

    source_system     VARCHAR(50)  NOT NULL DEFAULT 'APTIAD',
    batch_id          UUID,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_fta PRIMARY KEY (fta_id),
    CONSTRAINT uq_nds_fta_aptiad_no UNIQUE (aptiad_no)
);

-- ---------------------------------------------------------------------------
-- nds.fta_member
-- Bridge table — normalizes ods.fta.member_countries TEXT[].
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.fta_member (
    fta_id        UUID         NOT NULL,
    country_code  VARCHAR(3)   NOT NULL,

    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_fta_member PRIMARY KEY (fta_id, country_code),
    CONSTRAINT fk_nds_fta_member_fta
        FOREIGN KEY (fta_id) REFERENCES nds.fta (fta_id),
    CONSTRAINT fk_nds_fta_member_country
        FOREIGN KEY (country_code) REFERENCES nds.country (country_code)
);

-- ---------------------------------------------------------------------------
-- nds.trade_transaction
-- Normalized trade fact — FK references to country, product, time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.trade_transaction (
    trade_id          UUID           NOT NULL DEFAULT gen_random_uuid(),
    time_id           UUID           NOT NULL,
    hs_code           VARCHAR(8)     NOT NULL,
    hs_version        VARCHAR(10)    NOT NULL DEFAULT 'HS2017',
    partner_code      VARCHAR(3)     NOT NULL,
    flow_type         VARCHAR(10)    NOT NULL,
    value             NUMERIC(18,6),
    quantity          NUMERIC(18,6),
    unit              VARCHAR(20),
    record_source     VARCHAR(20),

    -- Lineage
    source_system     VARCHAR(50)    NOT NULL,
    batch_id          UUID           NOT NULL,
    is_late_arriving  BOOLEAN        NOT NULL DEFAULT FALSE,
    ods_id            UUID,

    created_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_trade_transaction PRIMARY KEY (trade_id),
    CONSTRAINT uq_nds_trade_transaction_grain UNIQUE (
        time_id, hs_code, hs_version, partner_code, flow_type, record_source
    ),
    CONSTRAINT chk_nds_trade_flow_type
        CHECK (flow_type IN ('Export', 'Import')),
    CONSTRAINT fk_nds_trade_time
        FOREIGN KEY (time_id) REFERENCES nds.time (time_id),
    CONSTRAINT fk_nds_trade_product
        FOREIGN KEY (hs_code, hs_version) REFERENCES nds.product (hs_code, hs_version),
    CONSTRAINT fk_nds_trade_partner
        FOREIGN KEY (partner_code) REFERENCES nds.country (country_code)
);

-- ---------------------------------------------------------------------------
-- nds.fta_utilization
-- Junction table — normalizes ods.trade_transaction.fta_keys TEXT[].
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.fta_utilization (
    trade_id   UUID         NOT NULL,
    fta_id     UUID         NOT NULL,

    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_fta_utilization PRIMARY KEY (trade_id, fta_id),
    CONSTRAINT fk_nds_fta_utilization_trade
        FOREIGN KEY (trade_id) REFERENCES nds.trade_transaction (trade_id),
    CONSTRAINT fk_nds_fta_utilization_fta
        FOREIGN KEY (fta_id) REFERENCES nds.fta (fta_id)
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_nds_country_name_trgm
    ON nds.country USING gin (country_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_nds_product_hs_version
    ON nds.product (hs_version);

CREATE INDEX IF NOT EXISTS ix_nds_trade_transaction_time_flow
    ON nds.trade_transaction (time_id, flow_type);

CREATE INDEX IF NOT EXISTS ix_nds_trade_transaction_partner
    ON nds.trade_transaction (partner_code);

CREATE INDEX IF NOT EXISTS ix_nds_trade_transaction_hs_code
    ON nds.trade_transaction (hs_code);

CREATE INDEX IF NOT EXISTS ix_nds_trade_transaction_ods_id
    ON nds.trade_transaction (ods_id);

CREATE INDEX IF NOT EXISTS ix_nds_fta_status
    ON nds.fta (status);

CREATE INDEX IF NOT EXISTS ix_nds_fta_member_country
    ON nds.fta_member (country_code);
