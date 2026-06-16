"""Transform stage.stage_exchange_rate rows into typed ODS records.

Reads directly from the stage table (not from a file artifact) so it is
consistent with the FTA stage-to-ODS pattern.

Transformations:
  • Cast rate_date TEXT → DATE.
  • Cast rate TEXT → NUMERIC(18,10); reject rows where rate <= 0.
  • Derive vnd_per_usd = 1 / rate  (1 USD expressed in VND).
  • Attach quality_flag 'RATE_INVALID' for any rejected rows (logged only —
    they do not reach ODS).
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
from common.chunking import DEFAULT_CHUNK_SIZE

logger = get_logger(__name__)

EXPECTED_COLS = [
    "rate_date",
    "base_currency",
    "quote_currency",
    "rate",
    "vnd_per_usd",
    "source_system",
    "batch_id",
]


def transform(df_stage: pd.DataFrame, batch_id: uuid.UUID) -> pd.DataFrame:
    """Return a clean DataFrame ready for ODS upsert."""
    df = df_stage.copy()

    # Cast date
    df["rate_date"] = pd.to_datetime(df["rate_date"], format="%Y-%m-%d", errors="coerce")
    bad_dates = df["rate_date"].isna()
    if bad_dates.any():
        logger.warning("RATE_INVALID: %d rows with bad rate_date — dropped", bad_dates.sum())
        df = df[~bad_dates]

    # Cast rate
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    bad_rates = df["rate"].isna() | (df["rate"] <= 0)
    if bad_rates.any():
        logger.warning("RATE_INVALID: %d rows with rate <= 0 — dropped", bad_rates.sum())
        df = df[~bad_rates]

    # Derive inverse rate for convenience
    df["vnd_per_usd"] = (1.0 / df["rate"]).round(6)

    df["source_system"] = "FRANKFURTER"
    df["batch_id"] = str(batch_id)

    return df[["rate_date", "base_currency", "quote_currency", "rate", "vnd_per_usd", "source_system", "batch_id"]].reset_index(drop=True)


def run(batch_id: uuid.UUID | None = None) -> tuple[pd.DataFrame, uuid.UUID]:
    """Fetch from stage and return transformed DataFrame + batch_id."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "exchange_rate_stage_to_ods")

    try:
        from sqlalchemy import text
        chunks = []
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT rate_date, base_currency, quote_currency, rate FROM stage.stage_exchange_rate")
            )
            while True:
                rows = result.fetchmany(DEFAULT_CHUNK_SIZE)
                if not rows:
                    break
                chunks.append(pd.DataFrame(rows, columns=["rate_date", "base_currency", "quote_currency", "rate"]))

        if not chunks:
            logger.warning("stage.stage_exchange_rate is empty — nothing to transform")
            df_out = pd.DataFrame(columns=EXPECTED_COLS)
        else:
            df_raw = pd.concat(chunks, ignore_index=True)
            logger.info("Read %d rows from stage.stage_exchange_rate", len(df_raw))
            df_out = transform(df_raw, batch_id)
            logger.info("Transform produced %d ODS-ready rows", len(df_out))

    except Exception as exc:
        logger.exception("exchange_rate_stage_to_ods failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    # Persist artifact for loader
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_file = tmp_dir / "exchange_rate_ods_ready.csv"
    df_out.to_csv(out_file, index=False)
    logger.info("Saved %d ODS-ready rows to %s", len(df_out), out_file)

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df_out))
    return df_out, batch_id


if __name__ == "__main__":
    run()
