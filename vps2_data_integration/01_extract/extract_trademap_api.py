"""
Phase 01a — Extract from TradeMap mock API (VPS1)

Responsibility:
  - Call the VPS1 API endpoints (/api/trade/flows, /api/trade/metadata).
  - Page through all results.
  - Bulk-insert raw records into stg.trade_flow_raw, stg.country_ref_raw,
    stg.hs_product_ref_raw.
  - TRUNCATE the target staging tables before loading (idempotent reload).

Entry point:
  run(batch_id: uuid.UUID | None = None) -> int
    Returns number of rows inserted into stg.trade_flow_raw.
  Can also be run directly: python 01_extract/extract_trademap_api.py

Available helpers (already wired):
  from config import load_config          # AppConfig with db DSN + VPS1_API_URL
  from common.db import (
      get_engine,                         # SQLAlchemy engine
      get_psycopg2_conn,                  # raw psycopg2 context manager
      register_batch, complete_batch,     # etl_batch_log helpers
  )
  from common.logging_config import setup_logging, get_logger
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
        batch_id = register_batch(engine, "extract_trademap_api")

    rows_loaded = 0
    try:
        # TODO: implement extraction logic
        # Suggested steps:
        #   1. TRUNCATE stg.trade_flow_raw, stg.country_ref_raw, stg.hs_product_ref_raw
        #   2. GET /api/trade/metadata  → insert into stg.country_ref_raw + stg.hs_product_ref_raw
        #   3. Paginate GET /api/trade/flows → bulk INSERT into stg.trade_flow_raw
        #   4. Set rows_loaded = total rows inserted
        raise NotImplementedError("TODO: implement extract_trademap_api.run()")
    except Exception as exc:
        logger.exception("extract_trademap_api failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
