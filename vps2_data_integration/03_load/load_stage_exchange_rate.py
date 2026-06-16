"""Load transformed exchange rate rows into stage.stage_exchange_rate.

Strategy: TRUNCATE the stage table and reload from the transformed artifact on
every run. Stage is a disposable landing zone; idempotency is enforced at ODS.
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
CREATE TABLE IF NOT EXISTS stage.stage_exchange_rate (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rate_date       TEXT NOT NULL,
    base_currency   TEXT NOT NULL,
    quote_currency  TEXT NOT NULL,
    rate            TEXT NOT NULL,
    source_system   TEXT NOT NULL DEFAULT 'FRANKFURTER',
    batch_id        UUID,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

UPSERT_SQL = """
INSERT INTO stage.stage_exchange_rate
    (rate_date, base_currency, quote_currency, rate, source_system, batch_id)
VALUES %s
"""


def _ensure_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS stage"))
        conn.execute(text(TABLE_DDL))
        conn.execute(text("TRUNCATE stage.stage_exchange_rate"))


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_exchange_rate")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "exchange_rate_transformed.csv"

        if not input_file.exists():
            logger.warning("Transformed exchange rate file not found at %s", input_file)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        df = pd.read_csv(input_file, dtype=str)
        if df.empty:
            logger.warning("No rows to load into stage — empty artifact")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        _ensure_table(engine)

        rows = [
            (
                row["rate_date"],
                row["base_currency"],
                row["quote_currency"],
                row["rate"],
                "FRANKFURTER",
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

        logger.info("Loaded %d rows into stage.stage_exchange_rate", len(rows))

    except Exception as exc:
        logger.exception("load_stage_exchange_rate failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(rows))
    return len(rows)


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
