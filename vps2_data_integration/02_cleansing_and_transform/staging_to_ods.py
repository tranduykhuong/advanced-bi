"""
Phase 02a — Staging → ODS

Promotes cleansed, type-cast records from stg.trade_flow_raw and
stg.gso_trade_raw into ods.trade_flow.

Transformations applied:
  • Cast VARCHAR columns to proper types (SMALLINT year, NUMERIC value/qty).
  • Normalise trade_flow to 'Export' | 'Import'.
  • Deduplicate on the natural grain key using ON CONFLICT DO UPDATE.
  • Mark rows as is_late_arriving where period_year < current watermark.
  • Update ods.etl_watermark after each source.
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


UPSERT_FROM_STG = text("""
INSERT INTO ods.trade_flow (
    reporter_code, partner_code, hs_code, period_year, trade_flow,
    trade_value_usd, quantity, quantity_unit,
    source_system, source_file, batch_id, is_late_arriving
)
SELECT
    UPPER(TRIM(s.reporter_code))                       AS reporter_code,
    UPPER(TRIM(s.partner_code))                        AS partner_code,
    TRIM(s.hs_code)                                    AS hs_code,
    s.period_year::SMALLINT                            AS period_year,
    CASE
        WHEN LOWER(TRIM(s.trade_flow)) LIKE '%export%' THEN 'Export'
        WHEN LOWER(TRIM(s.trade_flow)) LIKE '%import%' THEN 'Import'
    END                                                AS trade_flow,
    NULLIF(REGEXP_REPLACE(s.trade_value_usd, '[^0-9.]', '', 'g'), '')::NUMERIC AS trade_value_usd,
    NULLIF(REGEXP_REPLACE(s.quantity,        '[^0-9.]', '', 'g'), '')::NUMERIC AS quantity,
    NULLIF(TRIM(s.quantity_unit), '')                  AS quantity_unit,
    s.source_system,
    s.source_file,
    :batch_id::UUID,
    (s.period_year::SMALLINT < :watermark)             AS is_late_arriving
FROM stg.trade_flow_raw s
WHERE s.reporter_code IS NOT NULL
  AND s.partner_code   IS NOT NULL
  AND s.hs_code        IS NOT NULL
  AND s.period_year    ~ '^[0-9]{4}$'
  AND LOWER(TRIM(s.trade_flow)) IN ('export','import',
                                    'exports','imports',
                                    '1','2')
ON CONFLICT (reporter_code, partner_code, hs_code, period_year, trade_flow, source_system)
DO UPDATE SET
    trade_value_usd  = EXCLUDED.trade_value_usd,
    quantity         = EXCLUDED.quantity,
    quantity_unit    = EXCLUDED.quantity_unit,
    batch_id         = EXCLUDED.batch_id,
    is_late_arriving = EXCLUDED.is_late_arriving,
    updated_at       = NOW()
""")

UPSERT_FROM_GSO = text("""
INSERT INTO ods.trade_flow (
    reporter_code, partner_code, hs_code, period_year, trade_flow,
    trade_value_usd, quantity, quantity_unit,
    source_system, source_file, batch_id, is_late_arriving
)
SELECT
    UPPER(TRIM(g.reporter_code))                       AS reporter_code,
    UPPER(TRIM(g.partner_code))                        AS partner_code,
    TRIM(g.hs_code)                                    AS hs_code,
    g.report_year::SMALLINT                            AS period_year,
    CASE
        WHEN LOWER(TRIM(g.trade_flow)) LIKE '%export%' THEN 'Export'
        ELSE 'Import'
    END                                                AS trade_flow,
    NULLIF(REGEXP_REPLACE(g.trade_value_usd, '[^0-9.]', '', 'g'), '')::NUMERIC AS trade_value_usd,
    NULLIF(REGEXP_REPLACE(g.quantity,        '[^0-9.]', '', 'g'), '')::NUMERIC AS quantity,
    NULLIF(TRIM(g.quantity_unit), '')                  AS quantity_unit,
    g.source_system,
    g.source_file,
    :batch_id::UUID,
    (g.report_year::SMALLINT < :watermark)             AS is_late_arriving
FROM stg.gso_trade_raw g
WHERE g.reporter_code IS NOT NULL
  AND g.partner_code   IS NOT NULL
  AND g.hs_code        IS NOT NULL
  AND g.report_year    ~ '^[0-9]{4}$'
ON CONFLICT (reporter_code, partner_code, hs_code, period_year, trade_flow, source_system)
DO UPDATE SET
    trade_value_usd  = EXCLUDED.trade_value_usd,
    quantity         = EXCLUDED.quantity,
    quantity_unit    = EXCLUDED.quantity_unit,
    batch_id         = EXCLUDED.batch_id,
    is_late_arriving = EXCLUDED.is_late_arriving,
    updated_at       = NOW()
""")

UPSERT_COUNTRY_REF = text("""
INSERT INTO ods.country_ref (iso3_code, iso2_code, country_name, region, source_system, batch_id)
SELECT
    UPPER(TRIM(s.iso3_code)),
    UPPER(TRIM(s.iso2_code)),
    TRIM(s.country_name),
    TRIM(s.region),
    s.source_system,
    :batch_id::UUID
FROM stg.country_ref_raw s
WHERE s.iso3_code IS NOT NULL
ON CONFLICT (iso3_code, source_system)
DO UPDATE SET
    iso2_code    = EXCLUDED.iso2_code,
    country_name = EXCLUDED.country_name,
    region       = EXCLUDED.region,
    batch_id     = EXCLUDED.batch_id,
    updated_at   = NOW()
""")

UPSERT_HS_REF = text("""
INSERT INTO ods.hs_product_ref (hs_code, hs_chapter, description, hs_version, source_system, batch_id)
SELECT
    TRIM(s.hs_code),
    TRIM(s.hs_chapter),
    TRIM(s.description),
    COALESCE(NULLIF(TRIM(s.hs_version), ''), 'HS2017'),
    s.source_system,
    :batch_id::UUID
FROM stg.hs_product_ref_raw s
WHERE s.hs_code IS NOT NULL
ON CONFLICT (hs_code, hs_version, source_system)
DO UPDATE SET
    hs_chapter   = EXCLUDED.hs_chapter,
    description  = EXCLUDED.description,
    batch_id     = EXCLUDED.batch_id,
    updated_at   = NOW()
""")

UPDATE_WATERMARK = text("""
INSERT INTO ods.etl_watermark (source_system, max_period_year)
SELECT source_system, MAX(period_year)
FROM ods.trade_flow
WHERE source_system = :src
GROUP BY source_system
ON CONFLICT (source_system)
DO UPDATE SET
    max_period_year = EXCLUDED.max_period_year,
    last_updated    = NOW()
""")


def get_watermark(engine, source_system: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT max_period_year FROM ods.etl_watermark WHERE source_system = :src"),
            {"src": source_system},
        ).fetchone()
    return row[0] if row else 2000


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"staging_to_ods_{datetime.now(timezone.utc).date()}")

    try:
        wm_trademap = get_watermark(engine, "TRADEMAP_API")
        wm_gso      = get_watermark(engine, "GSO_CSV")
        logger.info("Watermarks — TRADEMAP_API: %d, GSO_CSV: %d", wm_trademap, wm_gso)

        with engine.begin() as conn:
            r1 = conn.execute(UPSERT_FROM_STG, {"batch_id": str(batch_id), "watermark": wm_trademap})
            logger.info("stg.trade_flow_raw → ods.trade_flow: %d rows affected.", r1.rowcount)

            r2 = conn.execute(UPSERT_FROM_GSO, {"batch_id": str(batch_id), "watermark": wm_gso})
            logger.info("stg.gso_trade_raw  → ods.trade_flow: %d rows affected.", r2.rowcount)

            r3 = conn.execute(UPSERT_COUNTRY_REF, {"batch_id": str(batch_id)})
            logger.info("stg.country_ref_raw → ods.country_ref: %d rows affected.", r3.rowcount)

            r4 = conn.execute(UPSERT_HS_REF, {"batch_id": str(batch_id)})
            logger.info("stg.hs_product_ref_raw → ods.hs_product_ref: %d rows affected.", r4.rowcount)

            for src in ("TRADEMAP_API", "UN_COMTRADE_CSV", "GSO_CSV"):
                conn.execute(UPDATE_WATERMARK, {"src": src})
            logger.info("ETL watermarks updated.")

        if managed_batch:
            complete_batch(engine, batch_id, rows_loaded=r1.rowcount + r2.rowcount)
    except Exception as exc:
        logger.exception("staging_to_ods failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise


if __name__ == "__main__":
    run()
