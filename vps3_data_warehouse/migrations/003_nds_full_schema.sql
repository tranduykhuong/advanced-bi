-- Migration 003: full NDS schema (3NF rebuild)
-- Drops legacy skeleton tables (dim_country, dim_hs_product, fact_trade_flow)
-- and creates the normalized nds layer aligned with ods.trade_transaction / ods.fta.

-- Drop legacy skeleton tables (order respects FK dependencies if any were added later)
DROP TABLE IF EXISTS nds.fact_trade_flow;
DROP TABLE IF EXISTS nds.dim_hs_product;
DROP TABLE IF EXISTS nds.dim_country;

-- Drop new tables in reverse dependency order (idempotent re-run)
DROP TABLE IF EXISTS nds.fta_utilization;
DROP TABLE IF EXISTS nds.trade_transaction;
DROP TABLE IF EXISTS nds.fta_member;
DROP TABLE IF EXISTS nds.fta;
DROP TABLE IF EXISTS nds.time;
DROP TABLE IF EXISTS nds.product;
DROP TABLE IF EXISTS nds.country;

-- ---------------------------------------------------------------------------
-- nds.country
-- ---------------------------------------------------------------------------
CREATE TABLE nds.country (
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
-- ---------------------------------------------------------------------------
CREATE TABLE nds.product (
    hs_code           VARCHAR(8)   NOT NULL,
    hs_version        VARCHAR(10)  NOT NULL DEFAULT 'HS2017',
    chapter_name  VARCHAR(100),
    heading_name  VARCHAR(100),
    product_name      VARCHAR(500),

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_product PRIMARY KEY (hs_code, hs_version)
);

-- ---------------------------------------------------------------------------
-- nds.time
-- ---------------------------------------------------------------------------
CREATE TABLE nds.time (
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
-- ---------------------------------------------------------------------------
CREATE TABLE nds.fta (
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
-- ---------------------------------------------------------------------------
CREATE TABLE nds.fta_member (
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
-- ---------------------------------------------------------------------------
CREATE TABLE nds.trade_transaction (
    trade_id          UUID           NOT NULL DEFAULT gen_random_uuid(),
    time_id           UUID           NOT NULL,
    hs_code           VARCHAR(8)     NOT NULL,
    hs_version        VARCHAR(10)    NOT NULL DEFAULT 'HS2017',
    partner_code      VARCHAR(3)     NOT NULL,
    flow_type         VARCHAR(10)    NOT NULL,
    value             NUMERIC(18,6),
    quantity          NUMERIC(18,6),
    unit              VARCHAR(20),
    source_system     VARCHAR(20)    NOT NULL,

    batch_id          UUID           NOT NULL,
    is_late_arriving  BOOLEAN        NOT NULL DEFAULT FALSE,
    ods_id            UUID,

    created_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_nds_trade_transaction PRIMARY KEY (trade_id),
    CONSTRAINT uq_nds_trade_transaction_grain UNIQUE (
        time_id, hs_code, hs_version, partner_code, flow_type, source_system
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
-- ---------------------------------------------------------------------------
CREATE TABLE nds.fta_utilization (
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
CREATE INDEX ix_nds_country_name_trgm
    ON nds.country USING gin (country_name gin_trgm_ops);

CREATE INDEX ix_nds_product_hs_version
    ON nds.product (hs_version);

CREATE INDEX ix_nds_trade_transaction_time_flow
    ON nds.trade_transaction (time_id, flow_type);

CREATE INDEX ix_nds_trade_transaction_partner
    ON nds.trade_transaction (partner_code);

CREATE INDEX ix_nds_trade_transaction_hs_code
    ON nds.trade_transaction (hs_code);

CREATE INDEX ix_nds_trade_transaction_ods_id
    ON nds.trade_transaction (ods_id);

CREATE INDEX ix_nds_fta_status
    ON nds.fta (status);

CREATE INDEX ix_nds_fta_member_country
    ON nds.fta_member (country_code);
