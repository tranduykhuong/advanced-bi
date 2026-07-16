-- =============================================================================
-- 011_ods_monitor_views.sql — Operational monitoring views on the ODS layer
-- Schema: ods
--
-- Backs the Saiku "ODS operations" cubes (ODS_Ingest_Monitor, ODS_Watermark)
-- so Saiku can chart pipeline health directly off the ODS layer:
--   1. Records ingested per day/hour, by source_system.
--   2. Late-arriving flow (is_late_arriving = TRUE), by source_system.
--   3. Data freshness / high-water mark per source (ods.etl_watermark).
--
-- Idempotent: CREATE OR REPLACE VIEW. Read-only over ods base tables.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Ingestion monitor — one row per ingested trade record.
--    is_late_arriving is cast to text: Mondrian wraps level predicates in
--    UPPER(), and UPPER(boolean) fails on PostgreSQL when a member is isolated.
--    ingest_date is a sortable YYYY-MM-DD string so the cube's time level
--    orders correctly on a line chart; ingest_hour is 0-23.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW ods.v_ingest_monitor AS
SELECT
    ods_id,
    source_system,
    is_late_arriving::text                       AS is_late_arriving,
    to_char(created_at, 'YYYY-MM-DD')            AS ingest_date,
    extract(hour  FROM created_at)::int          AS ingest_hour,
    batch_id
FROM ods.trade_transaction;

COMMENT ON VIEW ods.v_ingest_monitor IS
    'One row per ingested ods.trade_transaction record, exposing source_system, '
    'ingest date/hour (from created_at) and is_late_arriving (as text) for the '
    'Saiku ODS_Ingest_Monitor operational cube.';

-- ---------------------------------------------------------------------------
-- 2. Watermark monitor — per-source high-water mark + freshness.
--    hours_since_update = age of the last ODS load for that source. NOTE:
--    Mondrian caches results, so treat freshness as approximate (clear the
--    Saiku cache to refresh). max_period_year/month are the reliable measures.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW ods.v_watermark_monitor AS
SELECT
    source_system,
    max_period_year,
    max_period_month,
    last_updated,
    round(extract(epoch FROM (now() - last_updated)) / 3600.0, 1) AS hours_since_update
FROM ods.etl_watermark;

COMMENT ON VIEW ods.v_watermark_monitor IS
    'Per-source ETL high-water mark (max_period_year/month) and data freshness '
    '(hours_since_update) from ods.etl_watermark, for the Saiku ODS_Watermark cube.';
