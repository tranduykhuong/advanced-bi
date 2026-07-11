-- =============================================================================
-- 02_view_mondrian_cube.sql — Supporting views for the Mondrian OLAP cube
-- Schema: dds
--
-- Backs Vietnam_Trade_Analysis_Cube.mondrian.xml (Pentaho Schema Workbench),
-- built against dds (Dimensional Data Store) per report Section VI.
--
-- Views:
--   1. dds.dim_country_current  — SCD2 "current row only" filter
--   2. dds.dim_product_current  — SCD1 "current row only" filter
--   3. dds.dim_fta_current      — SCD1 "current row only" filter
--   4. dds.fact_trade_fta_bridge   — unnests fact_trade_transaction.fta_keys
--      (INTEGER[]) into one row per (trade_key, fta_key), since Mondrian
--      cannot join a dimension directly against an array column.
--   5. dds.fta_utilization_summary — per-FTA utilization rate, pre-aggregated
--      in SQL. A Mondrian Virtual Cube combining a distinct-count measure
--      from one cube with a measure from another (needed to compute
--      utilization live) proved unreliable on this PSW/Mondrian build
--      (ignoreUnrelatedDimensions did not prevent a divide-by-zero), so the
--      ratio is computed here instead and exposed as a plain measure.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1-3. SCD "current row" views
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
