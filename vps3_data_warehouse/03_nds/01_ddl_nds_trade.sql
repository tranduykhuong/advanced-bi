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
-- TODO: Uncomment and expand columns once ODS schema is finalized.
--       Add pg_trgm index on country_name for fuzzy matching support
--       (extension already enabled in 00_init.sql).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- nds.dim_country
-- Master country/territory reference (3NF, authoritative ISO codes).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.dim_country (
    country_id    SERIAL       NOT NULL,

    -- TODO: add master data columns
    -- iso3_code     CHAR(3)      NOT NULL,
    -- iso2_code     CHAR(2),
    -- country_name  VARCHAR(200) NOT NULL,
    -- region        VARCHAR(100),
    -- match_score   NUMERIC(5,2),   -- rapidfuzz reconciliation score (0–100)
    -- is_reconciled BOOLEAN      NOT NULL DEFAULT FALSE,

    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_dim_country PRIMARY KEY (country_id)

    -- TODO: CONSTRAINT uq_nds_country_iso3 UNIQUE (iso3_code)
);

-- Trigram index for fuzzy country name matching (uncomment after adding country_name column)
-- CREATE INDEX IF NOT EXISTS ix_nds_country_name_trgm
--     ON nds.dim_country USING gin (country_name gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- nds.dim_hs_product
-- Master HS commodity code reference.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.dim_hs_product (
    product_id    SERIAL       NOT NULL,

    -- TODO: add master data columns
    -- hs_code       VARCHAR(10)  NOT NULL,
    -- hs_chapter    CHAR(2)      NOT NULL,
    -- description   VARCHAR(500) NOT NULL,
    -- hs_version    VARCHAR(20)  NOT NULL DEFAULT 'HS2017',

    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_dim_hs_product PRIMARY KEY (product_id)

    -- TODO: CONSTRAINT uq_nds_hs_code_ver UNIQUE (hs_code, hs_version)
);

-- ---------------------------------------------------------------------------
-- nds.fact_trade_flow
-- Normalized 3NF trade fact — FK references to dim tables above.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nds.fact_trade_flow (
    fact_id          BIGSERIAL    NOT NULL,

    -- TODO: add FK columns and measures
    -- reporter_id      INTEGER      NOT NULL,  -- FK → nds.dim_country
    -- partner_id       INTEGER      NOT NULL,  -- FK → nds.dim_country
    -- product_id       INTEGER      NOT NULL,  -- FK → nds.dim_hs_product
    -- period_year      SMALLINT     NOT NULL,
    -- trade_flow       VARCHAR(10)  NOT NULL CHECK (trade_flow IN ('Export','Import')),
    -- trade_value_usd  NUMERIC(20,2),
    -- quantity         NUMERIC(20,4),
    -- quantity_unit    VARCHAR(20),

    -- Lineage (required — do not remove)
    source_system    VARCHAR(50)  NOT NULL,
    batch_id         UUID         NOT NULL,
    is_late_arriving BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_fact_trade_flow PRIMARY KEY (fact_id)

    -- TODO: add grain uniqueness constraint and FK constraints, e.g.:
    -- CONSTRAINT uq_nds_fact_grain    UNIQUE (reporter_id, partner_id, product_id,
    --                                         period_year, trade_flow, source_system),
    -- CONSTRAINT fk_nds_fact_reporter FOREIGN KEY (reporter_id) REFERENCES nds.dim_country,
    -- CONSTRAINT fk_nds_fact_partner  FOREIGN KEY (partner_id)  REFERENCES nds.dim_country,
    -- CONSTRAINT fk_nds_fact_product  FOREIGN KEY (product_id)  REFERENCES nds.dim_hs_product
);
