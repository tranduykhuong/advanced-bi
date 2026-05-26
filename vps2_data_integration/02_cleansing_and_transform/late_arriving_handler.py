"""
Phase 02c — Late-Arriving Data Handler

Detects rows in ods.trade_flow where is_late_arriving = TRUE and reprocesses
them through the NDS upsert path to ensure they are correctly represented in
the downstream star schema.

"Late arriving" means the row's period_year is lower than the current
high-watermark stored in ods.etl_watermark for that source system. This
commonly occurs when:
  - Historical data is backfilled (e.g. revised UN Comtrade statistics).
  - A source API re-delivers older periods in a new batch.

Strategy:
  1. Query ods.trade_flow WHERE is_late_arriving = TRUE.
  2. Re-resolve dimension FKs and upsert into nds.fact_trade_flow.
  3. Mark handled rows as is_late_arriving = FALSE so they won't be
     reprocessed unnecessarily in subsequent runs.
"""

from __future__ import annotations

import sys
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


REPROCESS_LATE_ROWS = text("""
INSERT INTO nds.fact_trade_flow (
    reporter_id, partner_id, product_id,
    period_year, trade_flow, trade_value_usd,
    quantity, quantity_unit, source_system, batch_id, is_late_arriving
)
SELECT
    rc.country_id,
    pc.country_id,
    pr.product_id,
    o.period_year,
    o.trade_flow,
    o.trade_value_usd,
    o.quantity,
    o.quantity_unit,
    o.source_system,
    :batch_id::UUID,
    TRUE   -- preserve the late-arriving flag in NDS for audit purposes
FROM ods.trade_flow o
JOIN nds.dim_country    rc ON rc.iso3_code = o.reporter_code
JOIN nds.dim_country    pc ON pc.iso3_code = o.partner_code
JOIN nds.dim_hs_product pr ON pr.hs_code   = o.hs_code
WHERE o.is_late_arriving = TRUE
ON CONFLICT (reporter_id, partner_id, product_id, period_year, trade_flow, source_system)
DO UPDATE SET
    trade_value_usd  = EXCLUDED.trade_value_usd,
    quantity         = EXCLUDED.quantity,
    quantity_unit    = EXCLUDED.quantity_unit,
    batch_id         = EXCLUDED.batch_id,
    is_late_arriving = TRUE,
    created_at       = nds.fact_trade_flow.created_at
""")

MARK_HANDLED = text("""
UPDATE ods.trade_flow
SET is_late_arriving = FALSE, updated_at = NOW()
WHERE is_late_arriving = TRUE
""")

COUNT_LATE = text("SELECT COUNT(*) FROM ods.trade_flow WHERE is_late_arriving = TRUE")


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"late_arriving_handler_{datetime.now(timezone.utc).date()}")

    try:
        with engine.connect() as conn:
            late_count = conn.execute(COUNT_LATE).scalar()

        if late_count == 0:
            logger.info("No late-arriving rows found — nothing to reprocess.")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        logger.info("Found %d late-arriving row(s) — reprocessing into NDS.", late_count)

        with engine.begin() as conn:
            result = conn.execute(REPROCESS_LATE_ROWS, {"batch_id": str(batch_id)})
            logger.info("Re-upserted %d NDS rows for late-arriving data.", result.rowcount)
            conn.execute(MARK_HANDLED)
            logger.info("Marked late-arriving ODS rows as handled.")

        if managed_batch:
            complete_batch(engine, batch_id, rows_loaded=result.rowcount)
        return result.rowcount

    except Exception as exc:
        logger.exception("late_arriving_handler failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise


if __name__ == "__main__":
    run()
