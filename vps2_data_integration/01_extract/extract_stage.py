from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

_TRADEMAP_BASE_FILTER = """
    product_code IS NOT NULL
    AND UPPER(TRIM(product_code)) != 'TOTAL'
    AND (
        TRIM(importer_name) ILIKE 'Viet Nam'
        OR TRIM(importer_name) ILIKE 'Vietnam'
        OR TRIM(exporter_name) ILIKE 'Viet Nam'
        OR TRIM(exporter_name) ILIKE 'Vietnam'
    )
"""


def _log_trademap_counts(conn, min_value_usd: float) -> None:
    """Log how many TRADE_MAP rows pass/fail the value filter."""
    count_sql = text(f"""
        SELECT
            COUNT(*) FILTER (WHERE COALESCE(value_usd_k, 0) * 1000 > :min_val) AS kept,
            COUNT(*) FILTER (WHERE NOT (COALESCE(value_usd_k, 0) * 1000 > :min_val)) AS dropped
        FROM stage.stage_db
        WHERE {_TRADEMAP_BASE_FILTER}
    """)
    row = conn.execute(count_sql, {"min_val": min_value_usd}).fetchone()
    logger.info(
        "TRADE_MAP rows: kept=%s, dropped=%s (TRADEMAP_MIN_VALUE_USD=%.2f)",
        row.kept,
        row.dropped,
        min_value_usd,
    )


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None

    if managed_batch:
        batch_id = register_batch(engine, "extract_stage")

    try:
        min_val = cfg.trademap_min_value_usd

        query = """
        SELECT 
            CAST(SUBSTRING(period::text, 1, 4) AS INTEGER) as year,
            CAST(SUBSTRING(period::text, 5, 2) AS INTEGER) as month,
            cmd_code as hs_code,
            cmd_desc as product_name,
            reporter_iso as partner_code,
            reporter_desc as partner_name,
            CASE WHEN LOWER(flow_desc) LIKE '%import%' THEN TRUE ELSE FALSE END as flow_type,
            primary_value as value,
            qty as quantity,
            qty_unit as unit,
            'UN_COMTRADE' as source_system
        FROM stage.stage_csv

        UNION ALL

        SELECT 
            year,
            month,
            NULL as hs_code,
            goods as product_name,
            NULL as partner_code,
            country as partner_name,
            flow_type,
            value,
            COALESCE(quantity, 0) as quantity,
            'ton' as unit,
            'NSO' as source_system
        FROM stage.stage_text

        UNION ALL

        SELECT
            year,
            month,
            product_code AS hs_code,
            product_label AS product_name,
            NULL AS partner_code,
            CASE
                WHEN TRIM(importer_name) ILIKE 'Viet Nam'
                  OR TRIM(importer_name) ILIKE 'Vietnam'
                THEN exporter_name
                WHEN TRIM(exporter_name) ILIKE 'Viet Nam'
                  OR TRIM(exporter_name) ILIKE 'Vietnam'
                THEN importer_name
            END AS partner_name,
            CASE
                WHEN TRIM(importer_name) ILIKE 'Viet Nam'
                  OR TRIM(importer_name) ILIKE 'Vietnam'
                THEN FALSE
                WHEN TRIM(exporter_name) ILIKE 'Viet Nam'
                  OR TRIM(exporter_name) ILIKE 'Vietnam'
                THEN TRUE
            END AS flow_type,
            value_usd_k * 1000 AS value,
            0 AS quantity,
            '' AS unit,
            'TRADE_MAP' AS source_system
        FROM stage.stage_db
        WHERE product_code IS NOT NULL
          AND UPPER(TRIM(product_code)) != 'TOTAL'
          AND (
              TRIM(importer_name) ILIKE 'Viet Nam'
              OR TRIM(importer_name) ILIKE 'Vietnam'
              OR TRIM(exporter_name) ILIKE 'Viet Nam'
              OR TRIM(exporter_name) ILIKE 'Vietnam'
          )
          AND COALESCE(value_usd_k, 0) * 1000 > :trademap_min_value_usd
        """

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        output_file = tmp_dir / "stage_extracted.csv"

        with engine.connect() as conn:
            _log_trademap_counts(conn, min_val)
            df = pd.read_sql_query(
                text(query), conn, params={"trademap_min_value_usd": min_val}
            )
        logger.info("Extracted %s rows (UNION ALL)", len(df))

        df.to_csv(output_file, index=False)

    except Exception as exc:
        logger.exception("extract_stage failed")

        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))

        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))

    return len(df)


if __name__ == "__main__":
    run()
