"""Load transformed Trade Map data into stage.stage_db table."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import Float, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.chunking import DEFAULT_CHUNK_SIZE
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

_transform = importlib.import_module("02_transform.transform_trademap_source")

logger = get_logger(__name__)

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_db (
    id BIGSERIAL PRIMARY KEY,
    exporter_name TEXT NOT NULL,
    importer_name TEXT NOT NULL,
    product_code TEXT NOT NULL,
    product_label TEXT,
    year INT NOT NULL,
    month INT NOT NULL,
    period TEXT NOT NULL,
    value_usd_k NUMERIC,
    batch_id TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_db_period
    ON stage.stage_db (period);
CREATE INDEX IF NOT EXISTS idx_stage_db_exporter
    ON stage.stage_db (exporter_name);
"""

_DTYPE = {
    "year": Float(),
    "month": Float(),
    "value_usd_k": Float(),
}


def run(batch_id: uuid.UUID | None = None) -> int:
    """Load Trade Map data into stage.stage_db."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_db")

    rows_loaded = 0
    try:
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))
            logger.info("Table schema initialized")

        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE stage.stage_db"))
            logger.info("Truncated stage.stage_db")

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        extracted_file = tmp_dir / "trademap_extracted.csv"
        transformed_file = tmp_dir / "trademap_transformed.csv"

        if not extracted_file.exists():
            logger.warning("Extracted Trade Map file not found at %s", extracted_file)
        else:
            _transform.transform_to_file()
            batch_id_str = str(batch_id)

            for chunk in pd.read_csv(transformed_file, chunksize=DEFAULT_CHUNK_SIZE):
                chunk["batch_id"] = batch_id_str
                chunk.to_sql(
                    "stage_db",
                    engine,
                    schema="stage",
                    if_exists="append",
                    index=False,
                    dtype=_DTYPE,
                )
                rows_loaded += len(chunk)

            logger.info("Loaded %d rows into stage.stage_db", rows_loaded)

    except Exception as exc:
        logger.exception("load_stage_db failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
