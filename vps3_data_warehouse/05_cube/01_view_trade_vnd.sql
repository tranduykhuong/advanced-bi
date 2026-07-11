-- =============================================================================
-- 01_view_trade_vnd.sql — Analytical cube: trade values in VND
-- Schema: cube
--
-- Purpose:
--   Pre-joined view that exposes nds.trade_transaction with VND-converted
--   values for Power BI and downstream OLAP queries.
--
-- Business rule for FX join:
--   For each (year, month) trade grain, the exchange rate used is the rate
--   from the LAST available trading day in that month
--   (MAX(rate_date) WHERE rate_date <= last day of month).
--   This avoids mid-month rates on monthly aggregate trade data and aligns
--   with standard trade-statistics reporting practice.
--
-- vnd_per_usd source: nds.exchange_rate.vnd_per_usd = 1 / rate
--   where rate = 1 VND expressed in USD (from Frankfurter API base=VND).
--
-- trade_value_vnd = value (USD) * vnd_per_usd
--
-- Rows where no rate is available for a given month return NULL for
-- trade_value_vnd and fx_rate_date — they do NOT fail the view.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS cube;

-- ---------------------------------------------------------------------------
-- Helper: last available rate per (year, month)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_monthly_fx_rate AS
SELECT
    EXTRACT(YEAR  FROM rate_date)::SMALLINT AS year,
    EXTRACT(MONTH FROM rate_date)::SMALLINT AS month,
    MAX(rate_date)                           AS fx_rate_date,
    -- vnd_per_usd at the last available day of the month
    (ARRAY_AGG(vnd_per_usd ORDER BY rate_date DESC))[1] AS vnd_per_usd
FROM nds.exchange_rate
WHERE base_currency  = 'VND'
  AND quote_currency = 'USD'
GROUP BY 1, 2;

COMMENT ON VIEW cube.v_monthly_fx_rate IS
    'Last-day-of-month VND/USD rate for each calendar month. '
    'Join with trade on (year, month) to convert USD → VND.';

-- ---------------------------------------------------------------------------
-- Main cube view: trade with VND conversion
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW cube.v_trade_vnd AS
SELECT
    -- Time
    t.year,
    t.month,
    t.quarter,

    -- Product
    p.hs_code,
    LEFT(p.hs_code, 2) AS hs_chapter,
    LEFT(p.hs_code, 4) AS hs_heading,
    p.category_heading,
    p.product_name,

    -- Partner country
    c.country_code    AS partner_code,
    c.country_name    AS partner_name,
    c.region          AS partner_region,
    c.continent       AS partner_continent,

    -- Trade flow
    tr.flow_type,
    tr.record_source,

    -- Original USD value
    tr.value          AS trade_value_usd,
    tr.quantity,
    tr.unit,

    -- FX conversion
    fx.fx_rate_date,
    fx.vnd_per_usd,
    CASE
        WHEN fx.vnd_per_usd IS NOT NULL AND tr.value IS NOT NULL
        THEN ROUND(tr.value * fx.vnd_per_usd, 2)
    END               AS trade_value_vnd,

    -- Lineage
    tr.source_system,
    tr.is_late_arriving,
    tr.trade_id

FROM nds.trade_transaction  tr
JOIN nds.time               t   ON t.time_id      = tr.time_id
JOIN nds.product            p   ON p.hs_code      = tr.hs_code
                                AND p.hs_version   = tr.hs_version
JOIN nds.country            c   ON c.country_code = tr.partner_code
LEFT JOIN cube.v_monthly_fx_rate fx
                                ON fx.year  = t.year
                               AND fx.month = t.month;

COMMENT ON VIEW cube.v_trade_vnd IS
    'Trade transactions with VND conversion via last-day-of-month exchange rate. '
    'trade_value_vnd is NULL when no FX rate is available for that month.';
