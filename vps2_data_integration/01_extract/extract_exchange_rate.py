"""Extract daily VND/USD exchange rates from Frankfurter API v2 into a CSV artifact.

Delta strategy:
  • Reads the last loaded date from ods.etl_watermark (source_system='FRANKFURTER').
  • Requests from (last_date - 7 days) to today to cover potential Frankfurter
    blended-rate revisions on recent days.
  • On the very first run, falls back to FRANKFURTER_FROM_DATE env var (default 1999-01-04,
    the earliest date the ECB/Frankfurter series begins).

Output:
  tmp/exchange_rate_extracted.csv  — date,base,quote,rate (v2 CSV format)
  raw_data/frankfurter/<YYYY-MM-DD>.csv  — audit snapshot per extract run
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

_OVERLAP_DAYS = 7          # re-fetch the last N days to catch blended-rate revisions
_DEFAULT_FROM  = "1999-01-04"  # earliest ECB/Frankfurter history


def _read_watermark(engine) -> date | None:
    """Return MAX(rate_date) already in ods.exchange_rate, or None if table is empty."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT MAX(rate_date) FROM ods.exchange_rate "
                    "WHERE base_currency = 'VND' AND quote_currency = 'USD'"
                )
            ).first()
        if row and row[0]:
            return row[0]
    except Exception as exc:
        logger.warning("Could not read ODS watermark: %s — will use FRANKFURTER_FROM_DATE", exc)
    return None


def _fetch_rates_csv(base_url: str, from_date: str, base: str, quotes: str) -> pd.DataFrame:
    """Call Frankfurter v2 CSV endpoint and return a DataFrame with columns date,base,quote,rate."""
    url = f"{base_url}/v2/rates.csv"
    params = {"from": from_date, "base": base, "quotes": quotes}
    logger.info("Fetching %s params=%s", url, params)
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))
    # v2 CSV columns: date, base, quote, rate
    expected = {"date", "base", "quote", "rate"}
    if not expected.issubset(set(df.columns)):
        raise ValueError(f"Unexpected Frankfurter CSV columns: {list(df.columns)}")
    df = df.rename(columns={"date": "rate_date", "base": "base_currency", "quote": "quote_currency"})
    return df[["rate_date", "base_currency", "quote_currency", "rate"]]


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_exchange_rate")

    try:
        # Determine from_date
        watermark = _read_watermark(engine)
        if watermark:
            from_date = (watermark - timedelta(days=_OVERLAP_DAYS)).strftime("%Y-%m-%d")
            logger.info("Watermark found: %s — fetching from %s", watermark, from_date)
        else:
            from_date = cfg.frankfurter_from_date
            logger.info("No watermark — initial load from %s", from_date)

        df = _fetch_rates_csv(
            cfg.frankfurter_base_url,
            from_date,
            base="VND",
            quotes="USD",
        )

        if df.empty:
            logger.warning("Frankfurter returned no rows — nothing to load")
            if managed_batch:
                complete_batch(engine, batch_id, rows_extracted=0)
            return 0

        # Write artifact for next ETL phase
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        artifact = tmp_dir / "exchange_rate_extracted.csv"
        df.to_csv(artifact, index=False)
        logger.info("Saved %d rows to %s", len(df), artifact)

        # Audit snapshot
        raw_dir = Path(cfg.raw_data_path) / "frankfurter"
        try:
            raw_dir.mkdir(parents=True, exist_ok=True)
            snapshot = raw_dir / f"{date.today().isoformat()}.csv"
            df.to_csv(snapshot, index=False)
            logger.info("Audit snapshot saved to %s", snapshot)
        except Exception as exc:
            logger.warning("Could not save audit snapshot: %s", exc)

    except Exception as exc:
        logger.exception("extract_exchange_rate failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_extracted=len(df))
    return len(df)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
