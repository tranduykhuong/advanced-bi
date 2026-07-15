-- =============================================================================
-- 010_dds_cube_views.sql — Recreate the Mondrian OLAP cube support views
-- Schema: dds
--
-- WHY THIS MIGRATION EXISTS
--   Migration 009_dds_full_schema.sql DROPs the three SCD "current row" views
--   (dim_country_current / dim_product_current / dim_fta_current) so it can
--   ALTER the underlying dim_* tables — but it never recreates them. Because
--   the deploy workflow re-runs every migration on each deploy, those three
--   views vanished from production after every deploy, breaking the Saiku /
--   Mondrian cube ("Table 'dim_product_current' does not exist in database").
--
--   The cube views used to live only in 05_cube/02_view_mondrian_cube.sql,
--   which is NOT part of the migration set nor the init DDL, so nothing
--   recreated them automatically. This migration folds them into the deploy
--   pipeline: it runs right after 009 on every deploy and on fresh volumes,
--   guaranteeing the cube always has its views.
--
-- Idempotent: all CREATE OR REPLACE VIEW. Mirrors 05_cube/02_view_mondrian_cube.sql
-- (keep the two in sync if the cube changes).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1-3. SCD "current row" views (the ones 009 drops)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dds.dim_country_current AS
SELECT * FROM dds.dim_country WHERE is_current = TRUE;

COMMENT ON VIEW dds.dim_country_current IS
    'dds.dim_country filtered to is_current = TRUE (SCD2). Used as the dim_country hierarchy table in the Mondrian cube.';

CREATE OR REPLACE VIEW dds.dim_product_current AS
SELECT * FROM dds.dim_product WHERE is_current = TRUE;

COMMENT ON VIEW dds.dim_product_current IS
    'dds.dim_product filtered to is_current = TRUE (SCD1). Used as the dim_product hierarchy table in the Mondrian cube.';

CREATE OR REPLACE VIEW dds.dim_fta_current AS
SELECT * FROM dds.dim_fta WHERE is_current = TRUE;

COMMENT ON VIEW dds.dim_fta_current IS
    'dds.dim_fta filtered to is_current = TRUE (SCD1). Used as the dim_fta hierarchy table in the Mondrian cube.';

-- ---------------------------------------------------------------------------
-- 4. FTA bridge — unnest the many-to-many fta_keys array
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dds.fact_trade_fta_bridge AS
SELECT
    f.trade_key,
    f.time_key,
    f.partner_key,
    f.product_key,
    f.value_vnd,
    unnest(f.fta_keys) AS fta_key
FROM dds.fact_trade_transaction f
WHERE f.fta_keys IS NOT NULL;

COMMENT ON VIEW dds.fact_trade_fta_bridge IS
    'One row per (trade_key, fta_key), unnesting fact_trade_transaction.fta_keys (INTEGER[]). '
    'Lets FTA_Utilization_Cube join dim_fta with a normal foreign key instead of an array column.';

-- ---------------------------------------------------------------------------
-- 5. FTA utilization summary — pre-aggregated rate per FTA
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dds.fta_utilization_summary AS
SELECT
    b.fta_key,
    COUNT(DISTINCT b.trade_key)                         AS fta_trade_count,
    (SELECT COUNT(*) FROM dds.fact_trade_transaction)    AS total_trade_count,
    ROUND(
        COUNT(DISTINCT b.trade_key)::numeric
        / NULLIF((SELECT COUNT(*) FROM dds.fact_trade_transaction), 0) * 100,
        2
    ) AS utilization_rate
FROM dds.fact_trade_fta_bridge b
GROUP BY b.fta_key;

COMMENT ON VIEW dds.fta_utilization_summary IS
    'Per-FTA trade count and utilization rate (percent of all Vietnam trade transactions that used that FTA). '
    'Backs FTA_Utilization_Cube.[Measures].[UtilizationRate] directly, avoiding cross-cube distinct-count in Mondrian.';
