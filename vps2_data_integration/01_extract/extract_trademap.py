"""
Extract ITC Trade Map relational data from VPS1 PostgreSQL (trademap_db).

Denormalizes trade_record via JOINs on country and product, then saves
a flat CSV snapshot to tmp/trademap_extracted.csv for downstream transform/load.

Uses a psycopg2 server-side cursor and csv.writer — no pandas — to stay
within memory limits on small VPS instances.
"""

from __future__ import annotations

import csv
import sys
import uuid
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.chunking import DEFAULT_CHUNK_SIZE
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

OUTPUT_COLUMNS = (
    "exporter_name",
    "importer_name",
    "product_code",
    "product_label",
    "year",
    "month",
    "value_usd_k",
)

EXTRACT_SQL = """
SELECT
    c_exp.name   AS exporter_name,
    c_imp.name   AS importer_name,
    tr.product_code,
    p.label      AS product_label,
    tr.year,
    tr.month,
    tr.value_usd_k
FROM trade_record tr
JOIN country c_exp ON c_exp.id = tr.exporter_id
JOIN country c_imp ON c_imp.id = tr.importer_id
LEFT JOIN product p ON p.code = tr.product_code
"""

COUNT_SQL = """
SELECT
    COUNT(*) AS total_rows,
    COUNT(DISTINCT tr.exporter_id) AS exporters,
    COUNT(DISTINCT tr.importer_id) AS importers
FROM trade_record tr
"""


def _stream_to_csv(cfg, output_file: Path, chunk_size: int) -> int:
    """Stream query results from VPS1 directly to CSV."""
    conn = psycopg2.connect(
        host=cfg.vps1_db.host,
        port=cfg.vps1_db.port,
        dbname=cfg.vps1_db.name,
        user=cfg.vps1_db.user,
        password=cfg.vps1_db.password,
    )
    rows_written = 0
    try:
        with conn:
            with conn.cursor(name="trademap_extract") as cur:
                cur.itersize = chunk_size
                cur.execute(EXTRACT_SQL)
                with output_file.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(OUTPUT_COLUMNS)
                    while True:
                        batch = cur.fetchmany(chunk_size)
                        if not batch:
                            break
                        writer.writerows(batch)
                        rows_written += len(batch)
                        if rows_written % chunk_size == 0:
                            logger.info("  → streamed %d rows...", rows_written)
    finally:
        conn.close()
    return rows_written


def _fetch_counts(cfg) -> tuple[int, int, int]:
    conn = psycopg2.connect(
        host=cfg.vps1_db.host,
        port=cfg.vps1_db.port,
        dbname=cfg.vps1_db.name,
        user=cfg.vps1_db.user,
        password=cfg.vps1_db.password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(COUNT_SQL)
            total, exporters, importers = cur.fetchone()
            return int(total), int(exporters), int(importers)
    finally:
        conn.close()


def run(batch_id: uuid.UUID | None = None) -> int:
    """Extract Trade Map rows from VPS1 and save to tmp/trademap_extracted.csv."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_trademap")

    rows_extracted = 0
    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "trademap_extracted.csv"
        if output_file.exists():
            output_file.unlink()

        total, exporters, importers = _fetch_counts(cfg)
        if total == 0:
            logger.warning(
                "No rows in trade_record — run ingest_trademap.py on VPS1 first."
            )
        else:
            logger.info(
                "trade_record has %d rows (%d exporters, %d importers) — streaming extract",
                total,
                exporters,
                importers,
            )

        rows_extracted = _stream_to_csv(cfg, output_file, DEFAULT_CHUNK_SIZE)
        logger.info("Saved %d rows to %s", rows_extracted, output_file)

    except Exception as exc:
        logger.exception("extract_trademap failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_extracted=rows_extracted)
    return rows_extracted


if __name__ == "__main__":
    run()
