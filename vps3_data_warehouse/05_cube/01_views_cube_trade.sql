-- =============================================================================
-- 01_views_cube_trade.sql — Analytical Cube Layer (SQL Views)
-- Schema: cube
--
-- These views define pre-aggregated analytical perspectives over the DDS
-- star schema — the "hypercube" slices accessible to BI tools (Metabase,
-- Power BI, Superset, etc.).
--
-- All views use only dds.* tables and dimension surrogate keys resolved
-- to human-readable attributes.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- cube.v_trade_by_country_year
-- Total trade value aggregated by reporter, partner, direction, and year.
-- Use case: bilateral trade balance, top-partner rankings.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_trade_by_country_year AS
SELECT
    dd_year.year                                           AS report_year,
    rep.country_bk                                         AS reporter_iso3,
    rep.country_name                                       AS reporter_name,
    rep.region                                             AS reporter_region,
    par.country_bk                                         AS partner_iso3,
    par.country_name                                       AS partner_name,
    par.region                                             AS partner_region,
    ft.trade_flow,
    SUM(ft.trade_value_usd)                                AS total_trade_value_usd,
    COUNT(*)                                               AS num_product_lines
FROM dds.fact_trade            ft
JOIN dds.dim_country           rep     ON ft.reporter_sk  = rep.country_sk AND rep.is_current
JOIN dds.dim_country           par     ON ft.partner_sk   = par.country_sk AND par.is_current
JOIN dds.dim_date              dd_year ON ft.date_year_sk = dd_year.date_sk
GROUP BY
    dd_year.year, rep.country_bk, rep.country_name, rep.region,
    par.country_bk, par.country_name, par.region, ft.trade_flow;

COMMENT ON VIEW cube.v_trade_by_country_year
    IS 'Cube: total bilateral trade value by reporter/partner/flow/year.';

-- ---------------------------------------------------------------------------
-- cube.v_trade_by_hs_chapter
-- Trade value aggregated by HS chapter (2-digit) and year.
-- Use case: commodity composition analysis, sector ranking.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_trade_by_hs_chapter AS
SELECT
    dd_year.year                   AS report_year,
    rep.country_bk                 AS reporter_iso3,
    rep.country_name               AS reporter_name,
    dp.hs_chapter,
    -- Chapter-level description derived from the lowest hs_code in chapter
    MIN(dp.description)            AS chapter_description_sample,
    ft.trade_flow,
    SUM(ft.trade_value_usd)        AS total_trade_value_usd,
    COUNT(DISTINCT dp.product_sk)  AS distinct_hs_codes
FROM dds.fact_trade            ft
JOIN dds.dim_country           rep     ON ft.reporter_sk  = rep.country_sk AND rep.is_current
JOIN dds.dim_product           dp      ON ft.product_sk   = dp.product_sk
JOIN dds.dim_date              dd_year ON ft.date_year_sk = dd_year.date_sk
GROUP BY
    dd_year.year, rep.country_bk, rep.country_name,
    dp.hs_chapter, ft.trade_flow;

COMMENT ON VIEW cube.v_trade_by_hs_chapter
    IS 'Cube: trade value by reporter, HS chapter (2-digit), trade direction, and year.';

-- ---------------------------------------------------------------------------
-- cube.v_trade_balance
-- Computed trade balance (Exports – Imports) per reporter × partner × year.
-- Use case: surplus/deficit analysis, trend visualization.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_trade_balance AS
WITH pivoted AS (
    SELECT
        dd_year.year                                  AS report_year,
        rep.country_bk                                AS reporter_iso3,
        rep.country_name                              AS reporter_name,
        par.country_bk                                AS partner_iso3,
        par.country_name                              AS partner_name,
        SUM(CASE WHEN ft.trade_flow = 'Export' THEN ft.trade_value_usd ELSE 0 END) AS export_usd,
        SUM(CASE WHEN ft.trade_flow = 'Import' THEN ft.trade_value_usd ELSE 0 END) AS import_usd
    FROM dds.fact_trade            ft
    JOIN dds.dim_country           rep     ON ft.reporter_sk  = rep.country_sk AND rep.is_current
    JOIN dds.dim_country           par     ON ft.partner_sk   = par.country_sk AND par.is_current
    JOIN dds.dim_date              dd_year ON ft.date_year_sk = dd_year.date_sk
    GROUP BY dd_year.year, rep.country_bk, rep.country_name,
             par.country_bk, par.country_name
)
SELECT
    report_year,
    reporter_iso3,
    reporter_name,
    partner_iso3,
    partner_name,
    export_usd,
    import_usd,
    (export_usd - import_usd) AS trade_balance_usd,
    CASE
        WHEN import_usd = 0 THEN NULL
        ELSE ROUND((export_usd / NULLIF(import_usd, 0) - 1) * 100, 2)
    END                        AS export_cover_ratio_pct
FROM pivoted;

COMMENT ON VIEW cube.v_trade_balance
    IS 'Cube: bilateral trade balance (exports minus imports) and export cover ratio.';

-- ---------------------------------------------------------------------------
-- cube.v_top_partners
-- Rolling top-10 trade partners per reporter per year by total trade value.
-- Use case: dashboard scorecards, partner concentration analysis.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_top_partners AS
SELECT
    report_year,
    reporter_iso3,
    reporter_name,
    partner_iso3,
    partner_name,
    total_trade_value_usd,
    num_product_lines,
    RANK() OVER (
        PARTITION BY report_year, reporter_iso3
        ORDER BY total_trade_value_usd DESC
    ) AS partner_rank
FROM cube.v_trade_by_country_year
WHERE trade_flow = 'Export';   -- rank by export value; change to 'Import' for top import sources

COMMENT ON VIEW cube.v_top_partners
    IS 'Cube: ranked export partners per reporter per year (rank by total export value).';

-- ---------------------------------------------------------------------------
-- cube.v_yoy_growth
-- Year-over-year trade value growth rate per reporter × partner × flow.
-- Use case: growth trend analysis, identifying emerging markets.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_yoy_growth AS
SELECT
    curr.report_year,
    curr.reporter_iso3,
    curr.reporter_name,
    curr.partner_iso3,
    curr.partner_name,
    curr.trade_flow,
    curr.total_trade_value_usd                  AS current_year_value,
    prev.total_trade_value_usd                  AS prior_year_value,
    ROUND(
        (curr.total_trade_value_usd - prev.total_trade_value_usd)
        / NULLIF(prev.total_trade_value_usd, 0) * 100,
        2
    )                                           AS yoy_growth_pct
FROM      cube.v_trade_by_country_year curr
LEFT JOIN cube.v_trade_by_country_year prev
       ON curr.reporter_iso3 = prev.reporter_iso3
      AND curr.partner_iso3  = prev.partner_iso3
      AND curr.trade_flow     = prev.trade_flow
      AND curr.report_year    = prev.report_year + 1;

COMMENT ON VIEW cube.v_yoy_growth
    IS 'Cube: year-over-year trade value growth rate per bilateral pair and trade direction.';
