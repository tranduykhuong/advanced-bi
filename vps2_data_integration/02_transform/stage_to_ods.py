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
        batch_id = register_batch(engine, "stage_to_ods")

    try:
        # TODO: implement stage → ODS transformation
        # Suggested steps:
        #   1. Query ods.etl_watermark for current high-watermark per source
        #   2. INSERT … ON CONFLICT DO UPDATE from stage.trade_flow_raw → ods.trade_flow
        #   3. INSERT … ON CONFLICT DO UPDATE from stage.gso_trade_raw   → ods.trade_flow
        #   4. Upsert stage.country_ref_raw  → ods.country_ref
        #   5. Upsert stage.hs_product_ref_raw → ods.hs_product_ref
        #   6. UPDATE ods.etl_watermark with new max(period_year) per source
        raise NotImplementedError("TODO: implement stage_to_ods.run()")
    except Exception as exc:
        logger.exception("stage_to_ods failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id)


if __name__ == "__main__":
    run()
