-- =============================================================================
-- 013_dds_forecast_clean_view.sql
--
-- Serving-layer cleaning view over dds.fact_trade_forecast (prophet_v1) that
-- powers the Trade_Forecast_Cube (Actual vs Forecast + confidence band, with
-- full product / partner / time / flow dimensions).
--
-- Grain: (time_key, product_key, partner_key, flow_type) — the SAME grain as
-- the forecast fact, so the cube can expose dim_product (chapter_name ->
-- product_key) and dim_partner (country_name keyed by partner_key).
--
-- Why the band stays correct after roll-up:
--   The confidence band is enforced PER ROW — forecast_lower <= forecast_vnd
--   <= forecast_upper and all >= 0. Summation preserves those inequalities, so
--   when Mondrian rolls the detail rows up to any level (month, chapter,
--   partner, All) the aggregated band is still ordered and non-negative.
--   (Clipping columns inconsistently per row — e.g. flooring lower but capping
--   upper — would break the ordering, so lower is tied to the point with
--   LEAST and upper with GREATEST.)
--
-- Cleaning applied:
--   * floor forecast/upper at 0 (trade value cannot be negative);
--   * cap forecast/upper at 3x the series' historical max (tames blow-ups);
--   * lower := min(lower, point) but >= 0; upper := max(upper, point);
--   * actual is restricted to the SAME (product,partner,flow) panel the
--     forecast covers, so Actual and Forecast compare on the same series;
--   * NULLs preserved: actual is NULL for future months (line ends after
--     history); forecast is NULL for pure-historical months (band starts at
--     the forecast horizon).
--
-- DATA-QUALITY CAVEAT: prophet_v1 forecasts run large and oscillate, and the
-- native CI is very tight. Treat the chart as INDICATIVE (trend + uncertainty
-- shape), not calibrated magnitudes, until the model is retrained
-- (log-transform + floor 0 + regularized changepoints + hold-out backtest).
--
-- Idempotent: CREATE OR REPLACE VIEW.
-- =============================================================================

CREATE OR REPLACE VIEW dds.v_trade_forecast_detail AS
WITH bounds AS (
    SELECT product_key, partner_key, flow_type,
           max(value_vnd) * 3 AS cap
    FROM dds.fact_trade_transaction
    GROUP BY product_key, partner_key, flow_type
),
fc AS (
    SELECT f.time_key, f.product_key, f.partner_key, f.flow_type,
           LEAST(GREATEST(f.forecasted_value, 0),
                 COALESCE(b.cap, GREATEST(f.forecasted_value, 0))) AS pt,
           GREATEST(f.yhat_lower, 0)                               AS lo_raw,
           LEAST(GREATEST(f.yhat_upper, 0),
                 COALESCE(b.cap, GREATEST(f.yhat_upper, 0)))       AS hi_raw
    FROM dds.fact_trade_forecast f
    LEFT JOIN bounds b USING (product_key, partner_key, flow_type)
),
panel AS (
    SELECT DISTINCT product_key, partner_key, flow_type
    FROM dds.fact_trade_forecast
),
act AS (
    SELECT t.time_key, t.product_key, t.partner_key, t.flow_type,
           sum(t.value_vnd) AS actual_vnd
    FROM dds.fact_trade_transaction t
    JOIN panel p USING (product_key, partner_key, flow_type)
    GROUP BY t.time_key, t.product_key, t.partner_key, t.flow_type
)
SELECT
    COALESCE(a.time_key,    f.time_key)    AS time_key,
    COALESCE(a.product_key, f.product_key) AS product_key,
    COALESCE(a.partner_key, f.partner_key) AS partner_key,
    COALESCE(a.flow_type,   f.flow_type)   AS flow_type,
    CASE WHEN a.actual_vnd IS NULL THEN NULL
         ELSE GREATEST(a.actual_vnd, 0) END              AS actual_vnd,
    f.pt                                                 AS forecast_vnd,
    CASE WHEN f.pt IS NULL THEN NULL
         ELSE GREATEST(LEAST(f.lo_raw, f.pt), 0) END     AS forecast_lower,  -- lower <= point, >= 0
    CASE WHEN f.pt IS NULL THEN NULL
         ELSE GREATEST(f.hi_raw, f.pt) END               AS forecast_upper   -- upper >= point
FROM act a
FULL OUTER JOIN fc f
  ON a.time_key    = f.time_key
 AND a.product_key = f.product_key
 AND a.partner_key = f.partner_key
 AND a.flow_type   = f.flow_type;

COMMENT ON VIEW dds.v_trade_forecast_detail IS
  'Cleaned (time_key, product_key, partner_key, flow_type) grain for Trade_Forecast_Cube: actual (same panel) vs prophet_v1 forecast with a per-row ordering-enforced, non-negative confidence band that stays coherent under roll-up. Forecast levels are indicative only pending model retrain.';
