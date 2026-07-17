"""XGBoost direct multi-horizon REGRESSOR: forecast the national trade
balance (Export - Import, USD) for each of the next RISK_WINDOW_MONTHS
individual months.

Reads exclusively from ods.trade_transaction, aggregated to a single
national monthly time series (Export, Import, Balance) — deliberately NOT
broken down by product/country, since that per-pair anomaly-detection job
belongs to problem 5's Isolation Forest, not this forecast.

Uses DIRECT multi-horizon forecasting: RISK_WINDOW_MONTHS separate
regressors, one per horizon k = 1..RISK_WINDOW_MONTHS, each predicting "what
will the trade balance be in month (this_month+k)" — all trained on ONLY
this month's real observed features (lags, growth rates), never a
simulated/recursive future. Every one of the 12 models looks at the exact
same current-month features, just trained against a different month's
target — predictions naturally get less sharp (converge toward the
historical average balance) as the horizon grows; that's an honest signal
about how little this month's snapshot says about a year from now, not a
bug.

is_high_risk flags only the DOWNSIDE direction (large deficit), since that's
the side of concern (problem 3's original framing: "phát hiện sớm rủi ro
thâm hụt"): is_high_risk(t) = 1 if predicted_balance(t) < risk_threshold_down,
where risk_threshold_down = mean - 2*std of the historical trade balance
series (the lower tail).

Each run TRUNCATEs mining.trade_balance_risk_prediction and writes exactly
RISK_WINDOW_MONTHS fresh rows — one per target_month = as_of_month + k for
k = 1..RISK_WINDOW_MONTHS. The table always holds only the latest run's
forecast, no history across runs. This output is a derived analytical
artifact, not integrated source data, so it lives in its own "mining"
schema rather than ods.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sqlalchemy import text
from xgboost import XGBRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

MODEL_VERSION = "xgb_v2_signed_balance"
RISK_WINDOW_MONTHS = 12  # one separate model + one output row per month 1..N ahead
MIN_ROWS = 12  # >= 3-month lag + a usable split; per-horizon fallback covers the rest
# Real data ceiling as of 2026-07: ods.trade_transaction only spans ~14 months
# (2025-04 to 2026-05), so far horizons (9-12 months ahead) have too few — or
# zero — valid (feature, label) pairs to fit a model at all (horizon 12 needs
# 3-month lag + 12-month forward label = 15 months of history just for ONE
# example). MIN_HORIZON_ROWS below gates each horizon individually: if a
# horizon doesn't have enough labeled rows, it falls back to a naive
# "persistence" prediction (today's balance) instead of crashing or fitting
# noise. Treat any fallback horizon as a placeholder, not a real forecast —
# it becomes a genuine model prediction automatically once enough months
# accumulate.
MIN_HORIZON_ROWS = 4
RISK_STD_MULTIPLIER = 2.0
TEST_FRACTION = 0.2

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS mining;

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
"""

# The table is TRUNCATEd before every insert (see run()).
INSERT_SQL = """
INSERT INTO mining.trade_balance_risk_prediction
    (target_month, horizon_months, predicted_balance, is_high_risk, risk_threshold_down, model_version, batch_id)
VALUES %s
"""

FEATURE_COLS = [
    "trade_balance",
    "export_usd",
    "import_usd",
    "mom_delta",
    "growth_rate_export",
    "growth_rate_import",
    "balance_lag_1",
    "balance_lag_2",
    "balance_lag_3",
    "month",
    "late_arriving_ratio",
]


def _load_monthly_balance(engine) -> pd.DataFrame:
    # late_arriving_ratio is read from public.late_arrival_audit (an append-only
    # audit trail, never updated/deleted) rather than
    # ods.trade_transaction.is_late_arriving directly — that flag is cleared by
    # late_arriving_handler.py once propagation to NDS is verified, so counting
    # it live would understate the historical late-arrival rate for any month
    # whose late rows have already been resolved.
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                WITH monthly AS (
                    SELECT
                        year,
                        month,
                        SUM(value) FILTER (WHERE flow_type)     AS export_usd,
                        SUM(value) FILTER (WHERE NOT flow_type) AS import_usd,
                        COUNT(*)                                AS total_count
                    FROM ods.trade_transaction
                    GROUP BY year, month
                ),
                late AS (
                    SELECT year, month, COUNT(*) AS late_count
                    FROM public.late_arrival_audit
                    GROUP BY year, month
                )
                SELECT
                    m.year,
                    m.month,
                    m.export_usd,
                    m.import_usd,
                    COALESCE(l.late_count, 0)::float / NULLIF(m.total_count, 0) AS late_arriving_ratio
                FROM monthly m
                LEFT JOIN late l ON l.year = m.year AND l.month = m.month
                ORDER BY m.year, m.month
                """
            )
        ).fetchall()
    return pd.DataFrame(
        rows, columns=["year", "month", "export_usd", "import_usd", "late_arriving_ratio"]
    )


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().sort_values(["year", "month"]).reset_index(drop=True)
    out["export_usd"] = out["export_usd"].astype(float).fillna(0.0)
    out["import_usd"] = out["import_usd"].astype(float).fillna(0.0)
    out["late_arriving_ratio"] = out["late_arriving_ratio"].astype(float).fillna(0.0)

    out["trade_balance"] = out["export_usd"] - out["import_usd"]
    out["mom_delta"] = out["trade_balance"].diff()
    out["growth_rate_export"] = out["export_usd"].pct_change()
    out["growth_rate_import"] = out["import_usd"].pct_change()
    out["balance_lag_1"] = out["trade_balance"].shift(1)
    out["balance_lag_2"] = out["trade_balance"].shift(2)
    out["balance_lag_3"] = out["trade_balance"].shift(3)
    return out


def compute_threshold_down(df: pd.DataFrame) -> float:
    """Lower-tail threshold for a 'risky' deficit = mean - 2*std of the
    historical trade balance level."""
    return float(df["trade_balance"].mean() - RISK_STD_MULTIPLIER * df["trade_balance"].std())


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def train_horizon(df: pd.DataFrame, k: int) -> float:
    """Train the horizon-k regressor on all history, log its holdout MAE/RMSE
    against a naive "persistence" baseline (predict next k months = this
    month's balance), and return the predicted balance for the single most
    recent row (the actual forward-looking prediction for target_month =
    as_of_month + k).

    Falls back to the naive persistence prediction itself (no model fit) when
    there aren't enough labeled rows for horizon k — see MIN_HORIZON_ROWS."""
    target = df["trade_balance"].shift(-k)
    working = df.assign(target=target)
    labeled = working.dropna(subset=FEATURE_COLS + ["target"]).reset_index(drop=True)

    if len(labeled) < MIN_HORIZON_ROWS:
        logger.warning(
            "trade_balance horizon=+%dmo: only %d labeled rows (< %d) — "
            "falling back to naive persistence (today's balance), not a real forecast",
            k, len(labeled), MIN_HORIZON_ROWS,
        )
        return float(df["trade_balance"].iloc[-1])

    split_idx = int(len(labeled) * (1 - TEST_FRACTION))
    train, test = labeled.iloc[:split_idx], labeled.iloc[split_idx:]

    model = XGBRegressor(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(train[FEATURE_COLS], train["target"])

    if len(test) > 0:
        pred = model.predict(test[FEATURE_COLS])
        mae = mean_absolute_error(test["target"], pred)
        rmse = float(np.sqrt(mean_squared_error(test["target"], pred)))
        naive_pred = test["trade_balance"].to_numpy()  # naive: "next k months = this month"
        naive_mae = mean_absolute_error(test["target"], naive_pred)
        naive_rmse = float(np.sqrt(mean_squared_error(test["target"], naive_pred)))
        logger.info(
            "trade_balance horizon=+%dmo holdout: MAE=%.0f RMSE=%.0f "
            "(naive 'persistence' baseline: MAE=%.0f RMSE=%.0f)  n_train=%d n_test=%d",
            k, mae, rmse, naive_mae, naive_rmse, len(train), len(test),
        )
    else:
        logger.warning("trade_balance horizon=+%dmo: holdout too small — skipping metrics", k)

    latest = df.dropna(subset=FEATURE_COLS).iloc[[-1]]
    return float(model.predict(latest[FEATURE_COLS])[0])


def _ensure_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(TABLE_DDL))


def _reset_table(engine) -> None:
    """Clear last run's forecast — the table only ever holds the latest one."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE mining.trade_balance_risk_prediction"))


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "risk_trade_balance_prediction")

    rows: list[tuple] = []
    try:
        raw = _load_monthly_balance(engine)
        if len(raw) < MIN_ROWS:
            raise NotImplementedError(
                f"Only {len(raw)} monthly rows in ods.trade_transaction — need >= {MIN_ROWS} "
                "for lag features and a meaningful train/test split"
            )

        features = build_features(raw)
        risk_threshold_down = compute_threshold_down(features)
        as_of_year = int(features["year"].iloc[-1])
        as_of_month_num = int(features["month"].iloc[-1])
        as_of_month = date(as_of_year, as_of_month_num, 1)

        # ods.trade_transaction lags behind real time (last observed month can
        # be weeks/months old), so the output window must be anchored to the
        # actual mining run date, not to as_of_month — otherwise target_month
        # starts in the past relative to when mining actually ran. mining_month
        # (the first not-yet-observed month) becomes horizon i=1;
        # data_gap_months converts each row's "months ahead of mining_month"
        # back into "months ahead of as_of_month", which is what train_horizon's
        # k actually shifts against. Clamped to >= 1 so k is never 0 (predicting
        # a month from its own feature row) even if ODS is fully caught up.
        mining_month = date.today().replace(day=1)
        data_gap_months = max(
            1,
            (mining_month.year - as_of_month.year) * 12
            + (mining_month.month - as_of_month.month),
        )

        for i in range(1, RISK_WINDOW_MONTHS + 1):
            k = data_gap_months + i - 1
            predicted_balance = train_horizon(features, k)
            target_month = _add_months(mining_month, i - 1)
            rows.append(
                (
                    target_month,
                    i,
                    predicted_balance,
                    predicted_balance < risk_threshold_down,
                    risk_threshold_down,
                    MODEL_VERSION,
                    str(batch_id),
                )
            )

        _ensure_table(engine)
        _reset_table(engine)

        conn_raw = psycopg2.connect(cfg.db.dsn)
        try:
            with conn_raw.cursor() as cur:
                execute_values(cur, INSERT_SQL, rows)
            conn_raw.commit()
        except Exception:
            conn_raw.rollback()
            raise
        finally:
            conn_raw.close()

        logger.info(
            "Reset mining.trade_balance_risk_prediction and inserted %d rows "
            "(as_of_month=%s, mining_month=%s)",
            len(rows), as_of_month, mining_month,
        )

    except NotImplementedError as exc:
        if managed_batch:
            complete_batch(engine, batch_id, status="SUCCESS", error_message=f"skipped: {exc}")
        raise
    except Exception as exc:
        logger.exception("risk_trade_balance_prediction failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(rows))
    return len(rows)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
