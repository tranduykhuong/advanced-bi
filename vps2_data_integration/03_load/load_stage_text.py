from __future__ import annotations

import csv
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, get_psycopg2_conn, register_batch, complete_batch

logger = get_logger(__name__)

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_text (
    id BIGSERIAL PRIMARY KEY,
    country TEXT,
    goods TEXT NOT NULL,
    flow_type BOOLEAN NOT NULL,
    quantity NUMERIC,
    value NUMERIC,
    month SMALLINT NOT NULL,
    year INTEGER NOT NULL
);
"""


def _ensure_table(engine):
    with engine.begin() as conn:
        conn.execute(text(TABLE_DDL))
        conn.execute(text("TRUNCATE stage.stage_text"))


def _load_csv_into_stage(csv_path: Path) -> int:
    total_rows = 0
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        total_rows = sum(1 for _ in csv.reader(fp)) - 1

    with get_psycopg2_conn(load_config()) as conn:
        with conn.cursor() as cursor, csv_path.open(
            "r", encoding="utf-8", newline=""
        ) as fp:
            cursor.copy_expert(
                "COPY stage.stage_text (country, goods, flow_type, quantity, value, month, year) FROM STDIN WITH CSV HEADER",
                fp,
            )
    return total_rows


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_text")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "stage_text_transformed.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Transformed artifact not found: {input_file}")

        _ensure_table(engine)
        rows_loaded = _load_csv_into_stage(input_file)
        logger.info("Loaded %s rows into stage.stage_text", rows_loaded)
    except Exception as exc:
        logger.exception("load_stage_text failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
