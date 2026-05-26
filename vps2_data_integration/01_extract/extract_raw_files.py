"""
Phase 01b — Extract from static raw files (CSV / Excel)

Responsibility:
  - Scan RAW_DATA_PATH for .csv / .xlsx / .xls files.
  - Route each file to the correct staging table based on filename pattern:
      "un_comtrade*"  → stg.trade_flow_raw
      "gso_trade*"    → stg.gso_trade_raw
  - Read with pandas, map source columns to staging columns, bulk-insert.

Entry point:
  run(batch_id: uuid.UUID | None = None) -> int
    Returns total rows inserted across all files.
  Can also be run directly: python 01_extract/extract_raw_files.py

Available helpers:
  from config import load_config
  from common.db import get_engine, get_psycopg2_conn, register_batch, complete_batch
  from common.logging_config import setup_logging, get_logger
  import pandas as pd          # in requirements.txt
  import openpyxl              # in requirements.txt (xlsx support for pandas)
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_raw_files")

    total_rows = 0
    try:
        raw_dir = Path(cfg.raw_data_path)
        if not raw_dir.exists():
            logger.warning("RAW_DATA_PATH '%s' not found — skipping.", raw_dir)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        # TODO: implement file extraction logic
        # Suggested steps:
        #   for filepath in raw_dir.iterdir():
        #     1. Detect file type and routing rule from filename
        #     2. pd.read_csv / pd.read_excel with dtype=str
        #     3. Rename columns to match staging DDL
        #     4. Bulk-insert rows into the target stg table
        #     5. Accumulate total_rows
        raise NotImplementedError("TODO: implement extract_raw_files.run()")
    except Exception as exc:
        logger.exception("extract_raw_files failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)
    return total_rows


if __name__ == "__main__":
    run()
