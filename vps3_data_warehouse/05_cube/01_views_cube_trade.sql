-- =============================================================================
-- 01_views_cube_trade.sql — Analytical Cube Layer (SQL Views)
-- Schema: cube
--
-- Design rules for this layer:
--   • Views ONLY — no base tables here.
--   • All views read exclusively from dds.* tables.
--   • Name views as cube.v_<topic>_<grain>.
--   • Views should be usable directly by BI tools (Metabase, Superset,
--     Power BI DirectQuery) without further transformation.
--
-- TODO: Implement views once dds.* columns are finalized.
--       Uncomment the examples below as a starting point.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- cube.v_trade_by_country_year
-- Total trade value by reporter / partner / direction / year.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE VIEW cube.v_trade_by_country_year AS
-- SELECT
--     dd.year                    AS report_year,
--     rep.country_bk             AS reporter_iso3,
--     rep.country_name           AS reporter_name,
--     par.country_bk             AS partner_iso3,
--     par.country_name           AS partner_name,
--     ft.trade_flow,
--     SUM(ft.trade_value_usd)    AS total_trade_value_usd,
--     COUNT(*)                   AS num_product_lines
-- FROM dds.fact_trade            ft
-- JOIN dds.dim_country           rep ON ft.reporter_sk  = rep.country_sk AND rep.is_current
-- JOIN dds.dim_country           par ON ft.partner_sk   = par.country_sk AND par.is_current
-- JOIN dds.dim_date              dd  ON ft.date_year_sk = dd.date_sk
-- GROUP BY dd.year, rep.country_bk, rep.country_name,
--          par.country_bk, par.country_name, ft.trade_flow;


-- ---------------------------------------------------------------------------
-- cube.v_trade_by_hs_chapter
-- Trade value by HS chapter (2-digit) / reporter / year.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE VIEW cube.v_trade_by_hs_chapter AS
-- SELECT
--     dd.year                        AS report_year,
--     rep.country_bk                 AS reporter_iso3,
--     rep.country_name               AS reporter_name,
--     dp.hs_chapter,
--     ft.trade_flow,
--     SUM(ft.trade_value_usd)        AS total_trade_value_usd,
--     COUNT(DISTINCT dp.product_sk)  AS distinct_hs_codes
-- FROM dds.fact_trade            ft
-- JOIN dds.dim_country           rep ON ft.reporter_sk  = rep.country_sk AND rep.is_current
-- JOIN dds.dim_product           dp  ON ft.product_sk   = dp.product_sk
-- JOIN dds.dim_date              dd  ON ft.date_year_sk = dd.date_sk
-- GROUP BY dd.year, rep.country_bk, rep.country_name, dp.hs_chapter, ft.trade_flow;


-- ---------------------------------------------------------------------------
-- cube.v_trade_balance
-- Exports − Imports per reporter / partner / year.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE VIEW cube.v_trade_balance AS
-- SELECT
--     report_year, reporter_iso3, reporter_name,
--     partner_iso3, partner_name,
--     SUM(CASE WHEN trade_flow = 'Export' THEN total_trade_value_usd ELSE 0 END) AS export_usd,
--     SUM(CASE WHEN trade_flow = 'Import' THEN total_trade_value_usd ELSE 0 END) AS import_usd,
--     SUM(CASE WHEN trade_flow = 'Export' THEN total_trade_value_usd ELSE 0 END)
--   - SUM(CASE WHEN trade_flow = 'Import' THEN total_trade_value_usd ELSE 0 END) AS trade_balance_usd
-- FROM cube.v_trade_by_country_year
-- GROUP BY report_year, reporter_iso3, reporter_name, partner_iso3, partner_name;


-- TODO: Add more views as required by your analytical requirements.
--       Common patterns to consider:
--         cube.v_top_partners       — RANK() by total trade value per reporter/year
--         cube.v_yoy_growth         — LAG() for year-over-year % growth
--         cube.v_hs_concentration   — Herfindahl index or top-N product share
