"""Extract APTIAD FTA CSV files from raw_data into tmp/aptiad_extracted.csv."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.chunking import DEFAULT_CHUNK_SIZE
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_aptiad")

    total_rows = 0
    try:
        raw_dir = Path(cfg.raw_data_path)
        csv_files = sorted(raw_dir.glob("APTIAD_*.csv"))

        if not csv_files:
            logger.warning("No APTIAD_*.csv files found in '%s' — skipping.", raw_dir)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "aptiad_extracted.csv"
        if output_file.exists():
            output_file.unlink()

        first_write = True
        for csv_file in csv_files:
            logger.info("Extracting APTIAD file: %s", csv_file.name)
            file_rows = 0

            for chunk in pd.read_csv(
                csv_file,
                low_memory=False,
                encoding="utf-8-sig",
                dtype=str,
                index_col=False,
                chunksize=DEFAULT_CHUNK_SIZE,
            ):
                chunk["__source_file__"] = csv_file.name
                chunk.to_csv(
                    output_file,
                    mode="w" if first_write else "a",
                    header=first_write,
                    index=False,
                )
                first_write = False
                file_rows += len(chunk)

            logger.info("  → Loaded %d rows from %s", file_rows, csv_file.name)
            total_rows += file_rows

        if total_rows:
            logger.info("Saved %d extracted rows to %s", total_rows, output_file)

    except Exception as exc:
        logger.exception("extract_aptiad failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)
    return total_rows


if __name__ == "__main__":
    run()
