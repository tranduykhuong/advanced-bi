"""Load extracted CSV data into stage.stage_csv table."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import importlib

import pandas as pd
from sqlalchemy import text, Float

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

_transform = importlib.import_module("02_transform.transform_csv_source")

logger = get_logger(__name__)

# DDL for stage.stage_csv table
TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_csv (
    id BIGSERIAL PRIMARY KEY,
    period TEXT,
    cmd_code TEXT,
    cmd_desc TEXT,
    reporter_iso TEXT,
    partner_iso TEXT,
    partner_desc TEXT,
    flow_code TEXT,
    flow_desc TEXT,
    primary_value NUMERIC,
    cif_value NUMERIC,
    fob_value NUMERIC,
    net_wgt NUMERIC,
    qty NUMERIC,
    qty_unit TEXT,
    mot_code TEXT,
    mot_desc TEXT,
    batch_id TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);
"""


def run(batch_id: uuid.UUID | None = None) -> int:
    """Load CSV extracted data into stage.stage_csv."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_csv")

    rows_loaded = 0
    try:
        # Initialize table schema
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))
            logger.info("Table schema initialized")

        # Clear existing data for fresh load
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE stage.stage_csv"))
            logger.info("Truncated stage.stage_csv")

        # Read extracted CSV data from temp location
        # Assuming extract_csv saves data to a temp file or database
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        csv_output = tmp_dir / "trade_extracted.csv"

        if csv_output.exists():
            df = _transform.run()

            # Insert into database
            df["batch_id"] = str(batch_id)
            df.to_sql(
                "stage_csv",
                engine,
                schema="stage",
                if_exists="append",
                index=False,
                dtype={
                    "primary_value": Float(),
                    "cif_value":     Float(),
                    "fob_value":     Float(),
                    "net_wgt":       Float(),
                    "qty":           Float(),
                },
            )
            rows_loaded = len(df)
            logger.info("Loaded %d rows into stage.stage_csv", rows_loaded)
        else:
            logger.warning("Extracted CSV file not found at %s", csv_output)

    except Exception as exc:
        logger.exception("load_stage_csv failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
