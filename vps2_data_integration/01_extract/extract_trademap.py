"""
Extract ITC Trade Map relational data from VPS1 PostgreSQL (trademap_db).

Denormalizes trade_record via JOINs on country and product, then saves
a flat CSV snapshot to tmp/trademap_extracted.csv for downstream transform/load.

Uses chunked reads to stay within memory limits on small VPS instances.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.chunking import DEFAULT_CHUNK_SIZE
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, get_vps1_engine, register_batch, complete_batch

logger = get_logger(__name__)


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

        vps1_engine = get_vps1_engine(cfg)
        exporters: set[str] = set()
        importers: set[str] = set()
        first_chunk = True

        try:
            for chunk in pd.read_sql(
                EXTRACT_SQL, vps1_engine, chunksize=DEFAULT_CHUNK_SIZE
            ):
                rows_extracted += len(chunk)
                exporters.update(chunk["exporter_name"].dropna().unique())
                importers.update(chunk["importer_name"].dropna().unique())
                chunk.to_csv(
                    output_file,
                    mode="w" if first_chunk else "a",
                    header=first_chunk,
                    index=False,
                )
                first_chunk = False
                del chunk
        finally:
            vps1_engine.dispose()

        if rows_extracted == 0:
            logger.warning(
                "No rows in trade_record — run ingest_trademap.py on VPS1 first."
            )
        else:
            logger.info(
                "Extracted %d rows (%d exporters, %d importers)",
                rows_extracted,
                len(exporters),
                len(importers),
            )

        logger.info("Saved extracted data to %s", output_file)

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
