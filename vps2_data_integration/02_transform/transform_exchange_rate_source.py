"""Transform raw Frankfurter extract into a clean stage-ready CSV artifact.

Input:  tmp/exchange_rate_extracted.csv  (date,base,quote,rate — raw strings)
Output: tmp/exchange_rate_transformed.csv (same columns, validated and deduplicated)

Transformations applied:
  • Parse rate_date as ISO date string; reject rows with non-parseable dates.
  • Cast rate to float; reject rows where rate <= 0 or NaN.
  • Normalise currency codes to upper-case, strip whitespace.
  • Deduplicate on (rate_date, base_currency, quote_currency) — keep last occurrence.
  • Log rows rejected to WARN so the pipeline stays auditable.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

EXPECTED_COLS = ["rate_date", "base_currency", "quote_currency", "rate"]


def _transform(df: pd.DataFrame) -> pd.DataFrame:
    initial_count = len(df)

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]
    for col in EXPECTED_COLS:
        if col not in df.columns:
            raise ValueError(f"Missing expected column '{col}' in extract artifact")

    df = df[EXPECTED_COLS].copy()

    # Currency codes: strip + upper
    df["base_currency"] = df["base_currency"].astype(str).str.strip().str.upper()
    df["quote_currency"] = df["quote_currency"].astype(str).str.strip().str.upper()

    # Parse date — coerce bad values to NaT
    df["rate_date"] = pd.to_datetime(df["rate_date"], format="%Y-%m-%d", errors="coerce")
    bad_dates = df["rate_date"].isna()
    if bad_dates.any():
        logger.warning("Dropping %d rows with unparseable rate_date", bad_dates.sum())
        df = df[~bad_dates]

    df["rate_date"] = df["rate_date"].dt.strftime("%Y-%m-%d")

    # Cast rate to numeric — coerce bad values to NaN
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    bad_rates = df["rate"].isna() | (df["rate"] <= 0)
    if bad_rates.any():
        logger.warning("Dropping %d rows with invalid rate (<= 0 or NaN)", bad_rates.sum())
        df = df[~bad_rates]

    # Deduplicate — keep last (most recent/revised) occurrence
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["rate_date", "base_currency", "quote_currency"], keep="last")
    if len(df) < before_dedup:
        logger.info("Deduplication removed %d rows", before_dedup - len(df))

    logger.info(
        "Transform complete: %d in → %d out (%d rejected)",
        initial_count,
        len(df),
        initial_count - len(df),
    )
    return df.reset_index(drop=True)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "transform_exchange_rate")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "exchange_rate_extracted.csv"

        if not input_file.exists():
            logger.warning(
                "Extracted exchange rate file not found at %s — skipping.", input_file
            )
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        df_raw = pd.read_csv(input_file, dtype=str)
        df_clean = _transform(df_raw)

        output_file = tmp_dir / "exchange_rate_transformed.csv"
        df_clean.to_csv(output_file, index=False)
        logger.info("Saved %d transformed rows to %s", len(df_clean), output_file)

    except Exception as exc:
        logger.exception("transform_exchange_rate failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df_clean))
    return len(df_clean)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
