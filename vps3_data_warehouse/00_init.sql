-- =============================================================================
-- 00_init.sql — Database Bootstrap
-- Creates the five warehouse schemas and required PostgreSQL extensions.
-- This script MUST run first (numeric prefix guarantees ordering).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS public;

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID primary key generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram similarity (fuzzy match support)
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- GiST index support for range types (SCD2)

-- Warehouse schemas (Hybrid Inmon-Kimball layers)
CREATE SCHEMA IF NOT EXISTS stage;  -- Stage:  raw landing zone (VARCHAR-heavy)
CREATE SCHEMA IF NOT EXISTS ods;   -- ODS:      operational data store (Inmon integrated)
CREATE SCHEMA IF NOT EXISTS nds;   -- NDS:      normalized data store (3NF master data)
CREATE SCHEMA IF NOT EXISTS dds;   -- DDS:      dimensional data store (Kimball star schema)

-- Metadata table to track ETL batch runs (accessible from all layers)
CREATE TABLE IF NOT EXISTS public.etl_batch_log (
    batch_id         UUID         NOT NULL DEFAULT uuid_generate_v4(),
    batch_name       VARCHAR(200) NOT NULL,
    started_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMPTZ,
    status           VARCHAR(20)  NOT NULL DEFAULT 'RUNNING'
                                  CHECK (status IN ('RUNNING','SUCCESS','FAILED')),
    rows_extracted   INTEGER,
    rows_loaded      INTEGER,
    rows_rejected    INTEGER      NOT NULL DEFAULT 0,
    rows_upserted    INTEGER      NOT NULL DEFAULT 0,
    error_message    TEXT,
    CONSTRAINT pk_etl_batch_log PRIMARY KEY (batch_id)
);

-- Reject records: rows dropped or flagged during Stage→ODS, ODS→NDS or NDS→DDS
-- for audit and data-lineage traceability.
CREATE TABLE IF NOT EXISTS public.reject_records (
    reject_id        BIGSERIAL    NOT NULL,
    batch_id         UUID         NOT NULL,
    process_type     SMALLINT     NOT NULL
                                  CHECK (process_type IN (1, 2, 3)),
                                  -- 1 = Stage -> ODS, 2 = ODS -> NDS, 3 = NDS -> DDS
    source_table     VARCHAR(100) NOT NULL,
    reject_reason    TEXT         NOT NULL,
    row_data         JSONB,
    rejected_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_reject_records PRIMARY KEY (reject_id),
    CONSTRAINT fk_reject_records_batch
        FOREIGN KEY (batch_id) REFERENCES public.etl_batch_log (batch_id)
);

CREATE INDEX IF NOT EXISTS ix_reject_records_batch_id
    ON public.reject_records (batch_id);

CREATE INDEX IF NOT EXISTS ix_reject_records_process_type
    ON public.reject_records (process_type);

COMMENT ON TABLE public.reject_records IS
    'Rows rejected/excluded during ETL (Stage->ODS=1, ODS->NDS=2, NDS->DDS=3). '
    'Used for audit and data traceability alongside etl_batch_log.';

COMMENT ON SCHEMA stage IS 'Stage Area — fast VARCHAR landing zone; truncated each ETL run';
COMMENT ON SCHEMA ods  IS 'Operational Data Store — typed, integrated, Inmon approach';
COMMENT ON SCHEMA nds  IS 'Normalized Data Store — 3NF master data and trade facts';
COMMENT ON SCHEMA dds  IS 'Dimensional Data Store — Kimball star schema (SCD2 on dim_country, dim_product, dim_fta)';
