-- Migration 011: mining schema — risk-prediction output tables
--
-- Stores the output of the two XGBoost risk mining models
-- (vps2_data_integration/04_mining/risk_exchange_rate_prediction.py — a
-- regressor forecasting signed % change — and
-- risk_trade_balance_prediction.py — a regressor forecasting the trade
-- balance level). Both models READ from ods.* (no NDS/DDS dependency, no
-- product/country dimension) but their OUTPUT is not itself
-- operational/integrated source data — it's a derived analytical artifact —
-- so it lives in its own "mining" schema rather than ods.
--
-- Note: both mining modules also self-create schema + table on first run
-- (CREATE SCHEMA/TABLE IF NOT EXISTS), so this migration is redundant-but-
-- safe — it just makes the schema available immediately after deploy
-- instead of waiting for the next mining run.
--
-- All statements are idempotent (IF NOT EXISTS).

CREATE SCHEMA IF NOT EXISTS mining;

-- Direct multi-horizon design: one row per target_date. Every mining run
-- TRUNCATEs this table first, then inserts RISK_WINDOW_DAYS (30) fresh rows,
-- target_date = today + k for k = 1..30, so the report can chart risk
-- day-by-day for the 30 days after the run. The table only ever holds the
-- latest run's forecast — no as_of_date column, no history across days.
--
-- Regressor (not classifier): predicted_change_pct is the SIGNED % change
-- forecast for target_date vs. the as-of rate; is_high_risk flags only the
-- upside (VND depreciation) direction against risk_threshold_up.
CREATE TABLE IF NOT EXISTS mining.exchange_rate_risk_prediction (
    prediction_id        UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date           DATE           NOT NULL,
    horizon_days          INT            NOT NULL,
    predicted_change_pct  NUMERIC(9,6)   NOT NULL,
    predicted_rate        NUMERIC(18,6)  NOT NULL,
    is_high_risk          BOOLEAN        NOT NULL,
    risk_threshold_up     NUMERIC(9,6)   NOT NULL,
    model_version         VARCHAR(30)    NOT NULL,
    batch_id              UUID           NOT NULL,
    predicted_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_mining_exchange_rate_risk_prediction UNIQUE (target_date, model_version)
);

CREATE INDEX IF NOT EXISTS idx_mining_exchange_rate_risk_prediction_target
    ON mining.exchange_rate_risk_prediction (target_date);

-- Direct multi-horizon design: one row per target_month. Every mining run
-- TRUNCATEs this table first, then inserts RISK_WINDOW_MONTHS (12) fresh
-- rows, target_month = this_month + k for k = 1..12, so the report can
-- chart the forecast month-by-month for the year after the run. The table
-- only ever holds the latest run's forecast — no history across runs.
--
-- Regressor (not classifier): predicted_balance is the forecast trade
-- balance level (Export - Import, USD) for target_month; is_high_risk
-- flags only the downside (large deficit) direction against
-- risk_threshold_down.
CREATE TABLE IF NOT EXISTS mining.trade_balance_risk_prediction (
    prediction_id        UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    target_month          DATE           NOT NULL,
    horizon_months         INT            NOT NULL,
    predicted_balance     NUMERIC(20,2)  NOT NULL,
    is_high_risk          BOOLEAN        NOT NULL,
    risk_threshold_down   NUMERIC(20,2)  NOT NULL,
    model_version         VARCHAR(30)    NOT NULL,
    batch_id              UUID           NOT NULL,
    predicted_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_mining_trade_balance_risk_prediction UNIQUE (target_month, model_version)
);

CREATE INDEX IF NOT EXISTS idx_mining_trade_balance_risk_prediction_target
    ON mining.trade_balance_risk_prediction (target_month);
