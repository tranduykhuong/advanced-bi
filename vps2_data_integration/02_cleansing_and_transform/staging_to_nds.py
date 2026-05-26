"""
Phase 02b — ODS → NDS (Normalized Data Store, 3NF)

Responsibility:
  - Merge ods.country_ref into nds.dim_country.
      • Use rapidfuzz to reconcile variant country name spellings across
        source systems (e.g. "Korea, Rep." vs "South Korea").
      • Store the match_score so data stewards can audit reconciled rows.
  - Upsert ods.hs_product_ref into nds.dim_hs_product.
  - Resolve reporter_code / partner_code / hs_code to integer FKs and
    upsert trade facts into nds.fact_trade_flow.

Entry point:
  run(batch_id: uuid.UUID | None = None) -> None
  Can also be run directly: python 02_cleansing_and_transform/staging_to_nds.py

Fuzzy matching (rapidfuzz — already in requirements.txt):
  from rapidfuzz import process as fz_process, fuzz
  match = fz_process.extractOne(dirty_name, known_names, scorer=fuzz.WRatio)
  # accept match if match[1] >= FUZZY_THRESHOLD (e.g. 80)

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

FUZZY_THRESHOLD = 80  # minimum rapidfuzz WRatio score to accept a match


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "staging_to_nds")

    try:
        # TODO: implement ODS → NDS normalization
        # Suggested steps:
        #   1. Load existing nds.dim_country rows (for fuzzy matching)
        #   2. For each row in ods.country_ref:
        #        a. Try exact ISO-3 match first
        #        b. Fall back to rapidfuzz name match against known country names
        #        c. Upsert into nds.dim_country with match_score
        #   3. Upsert ods.hs_product_ref → nds.dim_hs_product
        #   4. JOIN ods.trade_flow with nds dims to resolve FK IDs
        #      and upsert into nds.fact_trade_flow (ON CONFLICT DO UPDATE)
        raise NotImplementedError("TODO: implement staging_to_nds.run()")
    except Exception as exc:
        logger.exception("staging_to_nds failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id)


if __name__ == "__main__":
    run()
