"""XGBoost direct multi-horizon REGRESSOR: forecast the SIGNED % change in
the USD/VND exchange rate for each of the next RISK_WINDOW_DAYS individual
days (vnd_per_usd increasing = VND depreciating against USD).

Reads exclusively from ods.exchange_rate — no NDS/DDS dependency. Uses
DIRECT multi-horizon forecasting: RISK_WINDOW_DAYS separate regressors, one
per horizon k = 1..RISK_WINDOW_DAYS, each predicting "what % change (with
sign) will day (today+k) show versus today" — all trained on ONLY today's
real observed features (lag/rolling stats), never a simulated/recursive
future.

IMPORTANT — read before trusting the numbers: exchange rates are close to a
random walk (Meese-Rogoff, 1983 — one of the most replicated results in
international finance), so the best unbiased guess for a future rate is
often close to just "today's rate, no change". Each horizon's holdout is
logged against a naive "0% change" baseline (see train_horizon) — if a
horizon's MAE/RMSE isn't meaningfully better than the naive baseline, the
model has not found real signal at that horizon and predicted_change_pct
should be read as noise, not a genuine directional call.

is_high_risk flags only the UPSIDE direction (VND depreciation), since
that's the side of concern for import costs / USD-denominated debt:
is_high_risk(t) = 1 if predicted_change_pct(t) > risk_threshold_up, where
risk_threshold_up = mean + 2*std of the historical SIGNED daily % change
(the upper tail of the signed distribution — not the |change| distribution
used by the earlier classification design this replaced).

Each run TRUNCATEs mining.exchange_rate_risk_prediction and writes exactly
RISK_WINDOW_DAYS fresh rows — one per target_date = as_of_date + k for
k = 1..RISK_WINDOW_DAYS. The table always holds only the latest run's
forecast, no history across days. This output is a derived analytical
artifact, not integrated source data, so it lives in its own "mining"
schema rather than ods.
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
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

MODEL_VERSION = "xgb_v3_signed_change"
RISK_WINDOW_DAYS = 30  # one separate model + one output row per day 1..N ahead
MIN_ROWS = 120  # >= 30-day backward rolling window + enough rows for a usable split
RISK_STD_MULTIPLIER = 2.0
TEST_FRACTION = 0.2

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS mining;

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
"""

# The table is TRUNCATEd before every insert (see run()).
INSERT_SQL = """
INSERT INTO mining.exchange_rate_risk_prediction
    (target_date, horizon_days, predicted_change_pct, predicted_rate,
     is_high_risk, risk_threshold_up, model_version, batch_id)
VALUES %s
"""

FEATURE_COLS = [
    "vnd_per_usd",
    "change_pct",
    "rolling_volatility_7d",
    "rolling_volatility_30d",
    "rolling_mean_7d",
    "rolling_mean_30d",
    "lag_1",
    "lag_2",
    "lag_3",
    "day_of_week",
    "month",
]


def _load_series(engine) -> pd.DataFrame:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rate_date, vnd_per_usd FROM ods.exchange_rate "
                "WHERE base_currency = 'VND' AND quote_currency = 'USD' "
                "ORDER BY rate_date"
            )
        ).fetchall()
    df = pd.DataFrame(rows, columns=["rate_date", "vnd_per_usd"])
    # psycopg2 maps NUMERIC columns to decimal.Decimal, not float. Left as-is,
    # a column mixing Decimal with NaN (float) breaks pandas' vectorized
    # .mean()/.std() with "unsupported operand type(s) for -: 'float' and
    # 'decimal.Decimal'". Cast to float immediately after loading.
    df["vnd_per_usd"] = df["vnd_per_usd"].astype(float)
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Feature-engineer the daily VND/USD series. One row per rate_date.

    horizon_days below treats "k rows ahead" as "k days ahead", same
    approximation already used by lag_1/2/3 and the rolling windows —
    accurate as long as ods.exchange_rate has no large date gaps.
    """
    out = df.copy()
    out["rate_date"] = pd.to_datetime(out["rate_date"])
    out = out.sort_values("rate_date").reset_index(drop=True)

    out["change_pct"] = out["vnd_per_usd"].pct_change()
    out["rolling_volatility_7d"] = out["change_pct"].rolling(7).std()
    out["rolling_volatility_30d"] = out["change_pct"].rolling(30).std()
    out["rolling_mean_7d"] = out["change_pct"].rolling(7).mean()
    out["rolling_mean_30d"] = out["change_pct"].rolling(30).mean()
    out["lag_1"] = out["vnd_per_usd"].shift(1)
    out["lag_2"] = out["vnd_per_usd"].shift(2)
    out["lag_3"] = out["vnd_per_usd"].shift(3)
    out["day_of_week"] = out["rate_date"].dt.dayofweek
    out["month"] = out["rate_date"].dt.month
    return out


def compute_threshold_up(df: pd.DataFrame) -> float:
    """Upper-tail threshold for a 'risky' increase (VND depreciation) =
    mean + 2*std of the historical SIGNED daily % change. Deliberately not
    the |change| distribution — only the upside tail matters here."""
    return float(df["change_pct"].mean() + RISK_STD_MULTIPLIER * df["change_pct"].std())


def train_horizon(df: pd.DataFrame, k: int) -> float:
    """Train the horizon-k regressor on all history, log its holdout MAE/RMSE
    against a naive "0% change" (random-walk) baseline, and return the
    predicted signed % change for the single most recent row (the actual
    forward-looking prediction for target_date = as_of_date + k)."""
    target = df["change_pct"].shift(-k)
    working = df.assign(target=target)
    labeled = working.dropna(subset=FEATURE_COLS + ["target"]).reset_index(drop=True)

    split_idx = int(len(labeled) * (1 - TEST_FRACTION))
    train, test = labeled.iloc[:split_idx], labeled.iloc[split_idx:]

    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(train[FEATURE_COLS], train["target"])

    if len(test) > 0:
        pred = model.predict(test[FEATURE_COLS])
        mae = mean_absolute_error(test["target"], pred)
        rmse = float(np.sqrt(mean_squared_error(test["target"], pred)))
        naive_pred = np.zeros(len(test))  # naive baseline: "no change" (random-walk assumption)
        naive_mae = mean_absolute_error(test["target"], naive_pred)
        naive_rmse = float(np.sqrt(mean_squared_error(test["target"], naive_pred)))
        logger.info(
            "exchange_rate change horizon=+%dd holdout: MAE=%.5f RMSE=%.5f "
            "(naive 'no change' baseline: MAE=%.5f RMSE=%.5f)  n_train=%d n_test=%d",
            k, mae, rmse, naive_mae, naive_rmse, len(train), len(test),
        )
    else:
        logger.warning("exchange_rate change horizon=+%dd: holdout too small — skipping metrics", k)

    latest = df.dropna(subset=FEATURE_COLS).iloc[[-1]]
    return float(model.predict(latest[FEATURE_COLS])[0])


def _ensure_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(TABLE_DDL))


def _reset_table(engine) -> None:
    """Clear last run's forecast — the table only ever holds the latest one."""
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE mining.exchange_rate_risk_prediction"))


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "risk_exchange_rate_prediction")

    rows: list[tuple] = []
    try:
        raw = _load_series(engine)
        if len(raw) < MIN_ROWS:
            raise NotImplementedError(
                f"Only {len(raw)} rows in ods.exchange_rate — need >= {MIN_ROWS} "
                "for rolling features and a meaningful train/test split"
            )

        features = build_features(raw)
        risk_threshold_up = compute_threshold_up(features)
        as_of_date = features["rate_date"].iloc[-1].date()
        as_of_rate = float(features["vnd_per_usd"].iloc[-1])

        for k in range(1, RISK_WINDOW_DAYS + 1):
            predicted_change_pct = train_horizon(features, k)
            predicted_rate = as_of_rate * (1 + predicted_change_pct)
            target_date = as_of_date + timedelta(days=k)
            rows.append(
                (
                    target_date,
                    k,
                    predicted_change_pct,
                    predicted_rate,
                    predicted_change_pct > risk_threshold_up,
                    risk_threshold_up,
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
            "Reset mining.exchange_rate_risk_prediction and inserted %d rows (as_of_date=%s)",
            len(rows), as_of_date,
        )

    except NotImplementedError as exc:
        if managed_batch:
            complete_batch(engine, batch_id, status="SUCCESS", error_message=f"skipped: {exc}")
        raise
    except Exception as exc:
        logger.exception("risk_exchange_rate_prediction failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(rows))
    return len(rows)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
