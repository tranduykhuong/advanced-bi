# ODS DDL Patterns

## Standard Table Template

```sql
CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.{entity} (
    -- Surrogate key
    {entity}_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Business key columns (also defined in UNIQUE constraint below)
    natural_key     INTEGER NOT NULL,

    -- Business columns (typed)
    name            VARCHAR(300),
    status          VARCHAR(80),
    is_active       BOOLEAN,
    year_start      INTEGER,
    value           NUMERIC(18,6),
    tags            TEXT[],

    -- Lineage
    source_system   VARCHAR(50) NOT NULL DEFAULT '{SOURCE}',
    snapshot_date   DATE,
    batch_id        UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_{entity}_{key} UNIQUE (natural_key)
);
```

## ods.trade_transaction (Composite Business Key)

```sql
CREATE TABLE IF NOT EXISTS ods.trade_transaction (
    ods_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year                INTEGER NOT NULL,
    quarter             SMALLINT,
    month               SMALLINT NOT NULL,
    hs_code             VARCHAR(8),
    chapter_name    VARCHAR(100),
    heading_name    VARCHAR(100),
    product_name        VARCHAR(255),
    partner_code        VARCHAR(3),
    partner_name        VARCHAR(100),
    partner_region      VARCHAR(50),
    partner_continent   VARCHAR(50),
    fta_keys            TEXT[],
    flow_type           BOOLEAN NOT NULL,
    value               NUMERIC(18,6),
    quantity            NUMERIC(18,6),
    unit                VARCHAR(20),
    record_source       VARCHAR(20),
    source_system       VARCHAR(50) NOT NULL,
    batch_id            UUID NOT NULL,
    is_late_arriving    BOOLEAN DEFAULT FALSE,
    quality_flags       TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_trade_transaction
        UNIQUE (year, month, hs_code, partner_code, flow_type, record_source)
);
```

## ods.fta (Single Column Business Key)

```sql
CREATE TABLE IF NOT EXISTS ods.fta (
    fta_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aptiad_no                   INTEGER NOT NULL,
    fta_name                    VARCHAR(300),
    member_countries            TEXT[],
    status                      VARCHAR(80),
    scope                       VARCHAR(80),
    agreement_type              VARCHAR(120),
    is_upgraded                 BOOLEAN,
    year_signature_upgraded     INTEGER,
    year_enforcement_upgraded   INTEGER,
    has_trade_goods             BOOLEAN,
    year_signature_goods        INTEGER,
    year_enforcement_goods      INTEGER,
    has_trade_services          BOOLEAN,
    has_investment              BOOLEAN,
    provision_sps_tbt           BOOLEAN,
    provision_anti_dumping      BOOLEAN,
    provision_trade_facilitation BOOLEAN,
    -- ... other provision columns (all BOOLEAN) ...
    source_system               VARCHAR(50) NOT NULL DEFAULT 'APTIAD',
    snapshot_date               DATE,
    batch_id                    UUID,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_fta_aptiad_no UNIQUE (aptiad_no)
);
```
