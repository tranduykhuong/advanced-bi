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
    error_message    TEXT,
    CONSTRAINT pk_etl_batch_log PRIMARY KEY (batch_id)
);

COMMENT ON SCHEMA stage IS 'Stage Area — fast VARCHAR landing zone; truncated each ETL run';
COMMENT ON SCHEMA ods  IS 'Operational Data Store — typed, integrated, Inmon approach';
COMMENT ON SCHEMA nds  IS 'Normalized Data Store — 3NF master data and trade facts';
COMMENT ON SCHEMA dds  IS 'Dimensional Data Store — Kimball star schema (SCD1 & SCD2)';
