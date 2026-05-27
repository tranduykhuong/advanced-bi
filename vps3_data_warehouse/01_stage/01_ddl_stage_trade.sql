-- =============================================================================
-- 01_ddl_stage_trade.sql — Stage tables definition
-- Schema: stage
--
-- These tables store parsed monthly trade values from raw data sources.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage.stage_text (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    country TEXT,
    goods TEXT NOT NULL,
    flow_type BOOLEAN NOT NULL,
    quantity NUMERIC,
    value NUMERIC,
    month SMALLINT NOT NULL,
    year INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stage.stage_csv (
    id BIGSERIAL PRIMARY KEY,
    period VARCHAR(10) NOT NULL,
    cmd_code VARCHAR(10) NOT NULL,
    cmd_desc TEXT,
    reporter_iso VARCHAR(3),
    partner_iso VARCHAR(3),
    partner_desc TEXT,
    flow_code VARCHAR(5),
    flow_desc VARCHAR(50),
    primary_value NUMERIC,
    cif_value NUMERIC,
    fob_value NUMERIC,
    net_wgt NUMERIC,
    qty NUMERIC,
    qty_unit VARCHAR(10),
    mot_code VARCHAR(10),
    mot_desc TEXT,
    batch_id UUID,
    extracted_at TIMESTAMP DEFAULT NOW()
);
