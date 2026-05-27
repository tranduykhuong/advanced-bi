-- =============================================================================
-- 01_ddl_stage.sql — Stage tables definition
-- Schema: stage
--
-- These tables store parsed monthly trade values from raw data sources.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage.stage_text (
    id BIGSERIAL PRIMARY KEY,
    country TEXT,
    goods TEXT NOT NULL,
    flow_type BOOLEAN NOT NULL,
    quantity NUMERIC,
    value NUMERIC,
    month SMALLINT NOT NULL,
    year INTEGER NOT NULL
);
