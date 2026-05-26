-- =============================================================================
-- 01_ddl_nds_trade.sql — Normalized Data Store (NDS) Layer DDL
-- Schema: nds
--
-- Design principles (3NF Master Data):
--   • Fully normalized to Third Normal Form.
--   • Enforces referential integrity via foreign keys.
--   • Serves as the single source of truth for master data before
--     denormalization into the Kimball DDS star schema.
--   • Natural business keys are the primary identifiers here.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- nds.dim_country
-- Master country/territory reference — 3NF, authoritative ISO codes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.dim_country (
    country_id    SERIAL       NOT NULL,
    iso3_code     CHAR(3)      NOT NULL,
    iso2_code     CHAR(2),
    country_name  VARCHAR(200) NOT NULL,
    region        VARCHAR(100),
    -- Data quality columns from fuzzy matching
    match_score   NUMERIC(5,2),  -- rapidfuzz similarity score used to reconcile names
    is_reconciled BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_nds_dim_country      PRIMARY KEY (country_id),
    CONSTRAINT uq_nds_country_iso3     UNIQUE (iso3_code)
);

COMMENT ON COLUMN nds.dim_country.match_score
    IS 'Fuzzy match confidence (0–100) when country name was reconciled from dirty source names.';

CREATE INDEX IF NOT EXISTS ix_nds_country_iso3 ON nds.dim_country (iso3_code);
CREATE INDEX IF NOT EXISTS ix_nds_country_name_trgm
    ON nds.dim_country USING gin (country_name gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- nds.dim_hs_product
-- Master HS commodity code reference (3NF, keyed by code + version).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.dim_hs_product (
    product_id    SERIAL       NOT NULL,
    hs_code       VARCHAR(10)  NOT NULL,
    hs_chapter    CHAR(2)      NOT NULL,
    description   VARCHAR(500) NOT NULL,
    hs_version    VARCHAR(20)  NOT NULL DEFAULT 'HS2017',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_nds_dim_hs_product   PRIMARY KEY (product_id),
    CONSTRAINT uq_nds_hs_code_ver      UNIQUE (hs_code, hs_version)
);

CREATE INDEX IF NOT EXISTS ix_nds_hs_chapter ON nds.dim_hs_product (hs_chapter);

-- ---------------------------------------------------------------------------
-- nds.fact_trade_flow
-- Normalized, 3NF trade fact table referencing master data FKs.
-- This is the Inmon integration point — no denormalization yet.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.fact_trade_flow (
    fact_id         BIGSERIAL    NOT NULL,
    reporter_id     INTEGER      NOT NULL,
    partner_id      INTEGER      NOT NULL,
    product_id      INTEGER      NOT NULL,
    period_year     SMALLINT     NOT NULL,
    trade_flow      VARCHAR(10)  NOT NULL CHECK (trade_flow IN ('Export','Import')),
    trade_value_usd NUMERIC(20,2),
    quantity        NUMERIC(20,4),
    quantity_unit   VARCHAR(20),
    -- Lineage
    source_system   VARCHAR(50)  NOT NULL,
    batch_id        UUID         NOT NULL,
    is_late_arriving BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_nds_fact_trade_flow  PRIMARY KEY (fact_id),
    CONSTRAINT uq_nds_fact_grain       UNIQUE (reporter_id, partner_id, product_id,
                                               period_year, trade_flow, source_system),
    CONSTRAINT fk_nds_fact_reporter    FOREIGN KEY (reporter_id)
                                       REFERENCES nds.dim_country (country_id),
    CONSTRAINT fk_nds_fact_partner     FOREIGN KEY (partner_id)
                                       REFERENCES nds.dim_country (country_id),
    CONSTRAINT fk_nds_fact_product     FOREIGN KEY (product_id)
                                       REFERENCES nds.dim_hs_product (product_id)
);

CREATE INDEX IF NOT EXISTS ix_nds_fact_reporter   ON nds.fact_trade_flow (reporter_id);
CREATE INDEX IF NOT EXISTS ix_nds_fact_partner    ON nds.fact_trade_flow (partner_id);
CREATE INDEX IF NOT EXISTS ix_nds_fact_product    ON nds.fact_trade_flow (product_id);
CREATE INDEX IF NOT EXISTS ix_nds_fact_year       ON nds.fact_trade_flow (period_year);

COMMENT ON TABLE nds.fact_trade_flow
    IS '3NF trade fact table — Inmon NDS layer before denormalization into DDS star schema.';
