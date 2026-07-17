-- =============================================================================
-- 013_dds_forecast_clean_view.sql
--
-- Serving-layer cleaning view over dds.fact_trade_forecast (prophet_v1) that
-- powers the Trade_Forecast_Cube fan chart (Actual vs Forecast + confidence
-- band).
--
-- Why this shape:
--   * Grain is (time_key, flow_type). Aggregating the raw yhat / yhat_lower /
--     yhat_upper by SUM *before* any clipping keeps the band ordered
--     (sum(lower) <= sum(yhat) <= sum(upper)); clipping each column per-row
--     first would break that ordering.
--   * Non-negativity + band ordering are then enforced at the aggregate
--     (trade value cannot be negative; lower<=point<=upper).
--   * Actual is restricted to the SAME (product,partner,flow) panel that the
--     forecast covers, so actual and forecast levels are on a comparable set
--     of series (the forecast only covers a subset of all series).
--   * NULLs are preserved: actual is NULL for future months (line ends after
--     history) and forecast is NULL for pure-historical months (line starts
--     at the forecast horizon) -> a proper fan chart.
--
-- DATA-QUALITY CAVEAT: prophet_v1 forecasts run orders of magnitude above the
-- same-panel actuals and oscillate month to month. Treat the chart as
-- INDICATIVE (trend + widening uncertainty), NOT calibrated magnitudes, until
-- the model is retrained (log-transform + floor 0 + regularized changepoints +
-- hold-out backtest). See the report data-quality section.
--
-- Idempotent: CREATE OR REPLACE VIEW.
-- =============================================================================

CREATE OR REPLACE VIEW dds.v_trade_forecast_monthly AS
WITH panel AS (
    -- series (product x partner x flow) that actually have a forecast
    SELECT DISTINCT product_key, partner_key, flow_type
    FROM dds.fact_trade_forecast
),
act AS (
    -- actuals restricted to the forecast panel, summed to (time, flow)
    SELECT t.time_key, t.flow_type, sum(t.value_vnd) AS actual_vnd
    FROM dds.fact_trade_transaction t
    JOIN panel p USING (product_key, partner_key, flow_type)
    GROUP BY t.time_key, t.flow_type
),
fc AS (
    -- sum RAW forecast columns so lower<=yhat<=upper survives aggregation
    SELECT time_key, flow_type,
           sum(forecasted_value) AS yhat,
           sum(yhat_lower)       AS lo,
           sum(yhat_upper)       AS hi
    FROM dds.fact_trade_forecast
    GROUP BY time_key, flow_type
),
j AS (
    SELECT COALESCE(a.time_key,  f.time_key)  AS time_key,
           COALESCE(a.flow_type, f.flow_type) AS flow_type,
           a.actual_vnd,
           f.yhat, f.lo, f.hi
    FROM act a
    FULL OUTER JOIN fc f
      ON a.time_key = f.time_key
     AND a.flow_type = f.flow_type
)
SELECT
    time_key,
    flow_type,
    -- keep NULL when there is no actual (future months) so the actual line ends
    CASE WHEN actual_vnd IS NULL THEN NULL
         ELSE GREATEST(actual_vnd, 0) END                    AS actual_vnd,
    -- keep NULL when there is no forecast (pure history) so the band starts late
    CASE WHEN yhat IS NULL THEN NULL
         ELSE GREATEST(yhat, 0) END                          AS forecast_vnd,
    CASE WHEN yhat IS NULL THEN NULL
         ELSE GREATEST(LEAST(lo, yhat), 0) END               AS forecast_lower,  -- lower <= point, >= 0
    CASE WHEN yhat IS NULL THEN NULL
         ELSE GREATEST(hi, yhat, 0) END                      AS forecast_upper   -- upper >= point
FROM j;

COMMENT ON VIEW dds.v_trade_forecast_monthly IS
  'Cleaned (time_key, flow_type) grain for the Trade_Forecast fan chart: actual (same panel) vs prophet_v1 forecast with an ordering-enforced, non-negative confidence band. Forecast levels are indicative only pending model retrain.';
