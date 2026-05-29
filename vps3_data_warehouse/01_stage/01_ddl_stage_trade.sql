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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

CREATE TABLE IF NOT EXISTS stage.stage_db (
    id BIGSERIAL PRIMARY KEY,
    exporter_name TEXT NOT NULL,
    importer_name TEXT NOT NULL,
    product_code TEXT NOT NULL,
    product_label TEXT,
    year INT NOT NULL,
    month INT NOT NULL,
    period TEXT NOT NULL,
    value_usd_k NUMERIC,
    batch_id TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_db_period ON stage.stage_db (period);
CREATE INDEX IF NOT EXISTS idx_stage_db_exporter ON stage.stage_db (exporter_name);
