"""Load ODS-ready exchange rate rows into ods.exchange_rate.

Uses UPSERT on the natural key (rate_date, base_currency, quote_currency).
On conflict, always overwrites with the latest values from the current batch
(rate may be revised by Frankfurter's blended calculation).

After loading, advances the ods.etl_watermark for source_system='FRANKFURTER'.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS ods.exchange_rate (
    rate_date       DATE           NOT NULL,
    base_currency   CHAR(3)        NOT NULL DEFAULT 'VND',
    quote_currency  CHAR(3)        NOT NULL DEFAULT 'USD',
    rate            NUMERIC(18,10) NOT NULL,
    vnd_per_usd     NUMERIC(18,6)  NOT NULL,
    source_system   VARCHAR(50)    NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID           NOT NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ods_exchange_rate UNIQUE (rate_date, base_currency, quote_currency)
);
"""

UPSERT_SQL = """
INSERT INTO ods.exchange_rate
    (rate_date, base_currency, quote_currency, rate, vnd_per_usd, source_system, batch_id)
VALUES %s
ON CONFLICT ON CONSTRAINT uq_ods_exchange_rate
DO UPDATE SET
    rate          = EXCLUDED.rate,
    vnd_per_usd   = EXCLUDED.vnd_per_usd,
    source_system = EXCLUDED.source_system,
    batch_id      = EXCLUDED.batch_id,
    updated_at    = NOW()
"""

WATERMARK_SQL = """
INSERT INTO ods.etl_watermark (source_system, max_period_year, last_updated)
VALUES ('FRANKFURTER', :yr, NOW())
ON CONFLICT (source_system) DO UPDATE SET
    max_period_year = GREATEST(ods.etl_watermark.max_period_year, EXCLUDED.max_period_year),
    last_updated    = NOW()
"""


def _ensure_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(TABLE_DDL))


def _advance_watermark(engine, max_year: int) -> None:
    with engine.begin() as conn:
        conn.execute(text(WATERMARK_SQL), {"yr": max_year})
    logger.info("Watermark advanced: FRANKFURTER max_period_year=%d", max_year)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_exchange_rate_to_ods")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "exchange_rate_ods_ready.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"ODS-ready artifact not found: {input_file}")

        df = pd.read_csv(input_file)
        if df.empty:
            logger.warning("No rows to upsert into ods.exchange_rate — empty artifact")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        _ensure_table(engine)

        rows = [
            (
                row["rate_date"],
                str(row["base_currency"]).strip(),
                str(row["quote_currency"]).strip(),
                float(row["rate"]),
                float(row["vnd_per_usd"]),
                str(row["source_system"]),
                str(batch_id),
            )
            for _, row in df.iterrows()
        ]

        import psycopg2
        conn_raw = psycopg2.connect(cfg.db.dsn)
        try:
            with conn_raw.cursor() as cur:
                execute_values(cur, UPSERT_SQL, rows)
            conn_raw.commit()
        except Exception:
            conn_raw.rollback()
            raise
        finally:
            conn_raw.close()

        logger.info("Upserted %d rows into ods.exchange_rate", len(rows))

        # Advance watermark based on max year in this batch
        df["rate_date"] = pd.to_datetime(df["rate_date"])
        max_year = int(df["rate_date"].dt.year.max())
        _advance_watermark(engine, max_year)

    except Exception as exc:
        logger.exception("load_exchange_rate_to_ods failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(rows))
    return len(rows)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
