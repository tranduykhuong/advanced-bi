"""
Phase 02c — Late-Arriving Data Handler

Responsibility:
  - Query ods.trade_flow WHERE is_late_arriving = TRUE.
  - Re-resolve dimension FKs and re-upsert affected rows into nds.fact_trade_flow.
  - Mark handled rows as is_late_arriving = FALSE in ods.trade_flow so they
    are not reprocessed in subsequent pipeline runs.

"Late arriving" means the row's period_year is behind the current
ods.etl_watermark for its source system. Typical causes:
  - Backfilled historical corrections from the source API.
  - Delayed CSV drops covering older reporting periods.

Entry point:
  run(batch_id: uuid.UUID | None = None) -> int
    Returns number of NDS rows re-upserted.
  Can also be run directly: python 02_transform/late_arriving_handler.py

Available helpers:
  from config import load_config
  from common.db import get_engine, register_batch, complete_batch
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
        batch_id = register_batch(engine, "late_arriving_handler")

    rows_reprocessed = 0
    try:
        # TODO: implement late-arriving data reprocessing
        # Suggested steps:
        #   1. SELECT COUNT(*) FROM ods.trade_flow WHERE is_late_arriving = TRUE
        #   2. If count == 0, log and return early
        #   3. Re-upsert those rows into nds.fact_trade_flow (same logic as ods_to_nds)
        #   4. UPDATE ods.trade_flow SET is_late_arriving = FALSE WHERE is_late_arriving = TRUE
        raise NotImplementedError("TODO: implement late_arriving_handler.run()")
    except Exception as exc:
        logger.exception("late_arriving_handler failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_reprocessed)
    return rows_reprocessed


if __name__ == "__main__":
    run()
