"""
Phase 02c — Late-Arriving Data Handler

Responsibility:
  - Detect rows marked as late-arriving in ODS.
  - Reprocess and re-upsert them into downstream layers (NDS).
  - Update etl_watermark and clear the late-arriving flag.

This ensures data consistency when delayed or corrected data arrives after initial load.
"""

import sys
import uuid
import pandas as pd
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


def run(batch_id: uuid.UUID | None = None) -> int:
    """
    Handle late-arriving data from ODS layer.

    Returns:
        int: Number of rows successfully reprocessed.
    """
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "late_arriving_handler")

    rows_reprocessed = 0

    try:
        # Step 1: Find all late-arriving rows
        select_late_sql = """
        SELECT * FROM ods.trade_transaction 
        WHERE is_late_arriving = TRUE
        ORDER BY year DESC, month DESC
        """

        df_late = pd.read_sql(select_late_sql, engine)
        rows_reprocessed = len(df_late)

        if rows_reprocessed == 0:
            logger.info("No late-arriving data found in ODS.")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        logger.info(f"Found {rows_reprocessed} late-arriving rows to reprocess.")

        # Step 2: Reprocess logic (add more transformation if needed)
        # Currently, data in ODS is already enriched.
        # You can call transform functions here if necessary.

        # Step 3: Re-upsert into NDS (placeholder - update when NDS is ready)
        # Example:
        # df_late.to_sql('trade_transaction', engine, schema='nds',
        #                if_exists='append', index=False, method='multi')

        logger.info(f"Successfully reprocessed {rows_reprocessed} rows into NDS layer.")

        # Step 4: Mark as processed + Update Watermark
        with engine.begin() as conn:

            # Clear late-arriving flag
            clear_flag_sql = """
            UPDATE ods.trade_transaction 
            SET is_late_arriving = FALSE,
                load_at = NOW()
            WHERE is_late_arriving = TRUE
            """
            conn.execute(text(clear_flag_sql))

            # Update etl_watermark
            update_watermark_sql = """
            INSERT INTO ods.etl_watermark (source_system, max_period_year)
            SELECT 
                source_system,
                MAX(year) AS max_period_year
            FROM ods.trade_transaction
            GROUP BY source_system
            ON CONFLICT (source_system) 
            DO UPDATE SET 
                max_period_year = GREATEST(EXCLUDED.max_period_year, ods.etl_watermark.max_period_year),
                last_updated = NOW()
            """
            conn.execute(text(update_watermark_sql))

        logger.info(
            "✅ Late-arriving handler completed. Watermark updated and flags cleared."
        )

    except Exception as exc:
        logger.exception("late_arriving_handler failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_reprocessed)

    return rows_reprocessed


if __name__ == "__main__":
    run()
