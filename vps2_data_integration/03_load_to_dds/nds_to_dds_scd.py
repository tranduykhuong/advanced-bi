"""
Phase 03 — NDS → DDS (Dimensional Data Store, Star Schema)

Responsibility:
  - Apply SCD Type 2 to dds.dim_country:
      When country_name or region changes, expire the current row
      (valid_to = yesterday, is_current = FALSE) and insert a new version
      (valid_from = today, is_current = TRUE).
  - Apply SCD Type 1 to dds.dim_product:
      Overwrite description / hs_chapter in-place (no history retained).
  - Resolve NDS integer FKs → DDS surrogate keys and upsert dds.fact_trade
      on conflict (reporter_sk, partner_sk, product_sk, date_year_sk,
                   trade_flow, source_system).

Entry point:
  run(batch_id: uuid.UUID | None = None) -> None
  Can also be run directly: python 03_load_to_dds/nds_to_dds_scd.py

Key tables:
  nds.dim_country      → dds.dim_country  (SCD2)
  nds.dim_hs_product   → dds.dim_product  (SCD1)
  nds.fact_trade_flow  → dds.fact_trade   (via surrogate key resolution)

Date surrogate key convention:
  date_year_sk = YYYYMMDD integer for Jan 1 of the reporting year
  (e.g. 2022 → 20220101). Must exist in dds.dim_date (seeded in 04_dds DDL).

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


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "nds_to_dds_scd")

    try:
        # TODO: implement NDS → DDS SCD load
        # Suggested steps:
        #
        # --- SCD Type 2: dds.dim_country ---
        #   1. Load current dds.dim_country rows (is_current = TRUE)
        #   2. Compare against nds.dim_country
        #   3. For changed rows: UPDATE valid_to = yesterday, is_current = FALSE
        #   4. INSERT new version with valid_from = today, is_current = TRUE
        #   5. INSERT new business keys that don't exist yet in DDS
        #
        # --- SCD Type 1: dds.dim_product ---
        #   6. INSERT … ON CONFLICT (product_bk, hs_version) DO UPDATE
        #      (overwrite description, updated_at — no expiry)
        #
        # --- Fact load: dds.fact_trade ---
        #   7. JOIN nds.fact_trade_flow with dds dims (is_current rows for countries)
        #      to resolve reporter_sk, partner_sk, product_sk, date_year_sk
        #   8. INSERT … ON CONFLICT DO UPDATE
        raise NotImplementedError("TODO: implement nds_to_dds_scd.run()")
    except Exception as exc:
        logger.exception("nds_to_dds_scd failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id)


if __name__ == "__main__":
    run()
