"""
Phase — Late-Arriving Data Handler

Runs in the "ods-nds" phase group, immediately after 02_transform.ods_to_nds.

Why this runs *after* ods_to_nds (not before, as the original placeholder had
it): ods_to_nds upserts ods.trade_transaction into nds.trade_transaction by
business key (time, hs_code, partner_code, flow_type, source_system)
regardless of is_late_arriving — so a late-arriving row from the current
batch is already correctly re-upserted into NDS (and, downstream, DDS via
nds_to_dds_scd) by the time this handler runs.

Responsibility:
  - Find rows in ods.trade_transaction flagged is_late_arriving = TRUE.
  - Verify each one now has a matching row in nds.trade_transaction (joined
    via ods_id, which ods_to_nds always carries through).
  - Clear is_late_arriving for rows confirmed present in NDS.
  - For any late row NOT found in NDS (e.g. excluded by ods_to_nds's mandatory
    business-key filter — missing hs_code/partner_code), log it to
    public.reject_records for audit and leave its flag set so it is retried
    on the next pipeline run instead of silently disappearing.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch, log_reject_records

logger = get_logger(__name__)


_SQL_SELECT_LATE = text("""
    SELECT ods_id, year, month, hs_code, partner_code, flow_type, source_system
    FROM ods.trade_transaction
    WHERE is_late_arriving = TRUE
    ORDER BY year DESC, month DESC
""")

_SQL_SELECT_PROPAGATED = text("""
    SELECT ods_id
    FROM nds.trade_transaction
    WHERE ods_id = ANY(CAST(:ods_ids AS uuid[]))
""")

_SQL_CLEAR_FLAG = text("""
    UPDATE ods.trade_transaction
    SET is_late_arriving = FALSE,
        updated_at       = NOW()
    WHERE ods_id = ANY(CAST(:ods_ids AS uuid[]))
""")


def run(batch_id: uuid.UUID | None = None) -> int:
    """Verify and clear late-arriving rows. Returns the number cleared."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "late_arriving_handler")

    cleared = 0
    unresolved = 0

    try:
        with engine.connect() as conn:
            late_rows = conn.execute(_SQL_SELECT_LATE).fetchall()

        if not late_rows:
            logger.info("No late-arriving rows pending in ODS.")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        logger.info("Found %d late-arriving row(s) in ODS.", len(late_rows))

        ods_ids = [str(r.ods_id) for r in late_rows]
        with engine.connect() as conn:
            propagated = {
                str(r.ods_id)
                for r in conn.execute(
                    _SQL_SELECT_PROPAGATED, {"ods_ids": ods_ids}
                ).fetchall()
            }

        resolved_rows = [r for r in late_rows if str(r.ods_id) in propagated]
        unresolved_rows = [r for r in late_rows if str(r.ods_id) not in propagated]

        if resolved_rows:
            resolved_ids = [str(r.ods_id) for r in resolved_rows]
            with engine.begin() as conn:
                result = conn.execute(_SQL_CLEAR_FLAG, {"ods_ids": resolved_ids})
            cleared = result.rowcount
            logger.info(
                "Cleared is_late_arriving on %d row(s) confirmed in nds.trade_transaction.",
                cleared,
            )

        if unresolved_rows:
            unresolved = len(unresolved_rows)
            log_reject_records(
                engine,
                batch_id,
                process_type=2,
                source_table="ods.trade_transaction",
                reject_reason="late_arriving_not_yet_propagated_to_nds",
                rows=[
                    {
                        "ods_id": str(r.ods_id),
                        "year": r.year,
                        "month": r.month,
                        "hs_code": r.hs_code,
                        "partner_code": r.partner_code,
                        "flow_type": r.flow_type,
                        "source_system": r.source_system,
                    }
                    for r in unresolved_rows
                ],
            )
            logger.warning(
                "%d late-arriving row(s) not yet found in NDS — flag left set, "
                "logged to reject_records for retry on the next run.",
                unresolved,
            )

        logger.info(
            "Late-arriving handler complete: %d cleared, %d unresolved (of %d total).",
            cleared, unresolved, len(late_rows),
        )

    except Exception as exc:
        logger.exception("late_arriving_handler failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(
            engine,
            batch_id,
            rows_loaded=cleared,
            rows_rejected=unresolved,
            rows_upserted=cleared,
        )

    return cleared


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
