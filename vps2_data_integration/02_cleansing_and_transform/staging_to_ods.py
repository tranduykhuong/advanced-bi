"""
Phase 02a — Staging → ODS (Operational Data Store)

Responsibility:
  - Read from stg.trade_flow_raw and stg.gso_trade_raw.
  - Cast VARCHAR columns to proper types (SMALLINT year, NUMERIC values).
  - Normalise trade_flow values to 'Export' | 'Import'.
  - Deduplicate on the natural grain key.
  - Upsert into ods.trade_flow (ON CONFLICT DO UPDATE).
  - Flag rows as is_late_arriving where period_year < current watermark.
  - Update ods.etl_watermark after load.
  - Upsert reference data: stg.country_ref_raw → ods.country_ref,
                            stg.hs_product_ref_raw → ods.hs_product_ref.

Entry point:
  run(batch_id: uuid.UUID | None = None) -> None
  Can also be run directly: python 02_cleansing_and_transform/staging_to_ods.py

Watermark helper (example):
  SELECT max_period_year FROM ods.etl_watermark WHERE source_system = 'TRADEMAP_API'

Available helpers:
  from config import load_config
  from common.db import get_engine, register_batch, complete_batch
  from common.logging_config import setup_logging, get_logger
  from sqlalchemy import text   # for parameterised SQL
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


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "staging_to_ods")

    try:
        # TODO: implement staging → ODS transformation
        # Suggested steps:
        #   1. Query ods.etl_watermark for current high-watermark per source
        #   2. INSERT … ON CONFLICT DO UPDATE from stg.trade_flow_raw → ods.trade_flow
        #   3. INSERT … ON CONFLICT DO UPDATE from stg.gso_trade_raw   → ods.trade_flow
        #   4. Upsert stg.country_ref_raw  → ods.country_ref
        #   5. Upsert stg.hs_product_ref_raw → ods.hs_product_ref
        #   6. UPDATE ods.etl_watermark with new max(period_year) per source
        raise NotImplementedError("TODO: implement staging_to_ods.run()")
    except Exception as exc:
        logger.exception("staging_to_ods failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id)


if __name__ == "__main__":
    run()
