"""
Phase 03 — NDS → DDS (Dimensional Data Store, Star Schema)

Denormalizes master data from the NDS 3NF layer into Kimball dimensions
and loads the central fact table. Two SCD strategies are applied:

  SCD Type 2 — dds.dim_country
      When country_name or region changes, the existing current row is
      expired (valid_to = yesterday, is_current = FALSE) and a new row is
      inserted (valid_from = today, is_current = TRUE).

  SCD Type 1 — dds.dim_product
      When hs_description changes, the existing row is overwritten in-place.
      No historical versions are kept.

  dds.fact_trade — INSERT … ON CONFLICT DO UPDATE
      Fact rows are upserted on the natural grain key. Surrogate keys for
      dimension rows are resolved at load time.
"""

from __future__ import annotations

import sys
import uuid
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# SCD Type 2 — dds.dim_country
# ---------------------------------------------------------------------------

def load_dds_countries(engine) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(
            "SELECT country_sk, country_bk, country_name, region "
            "FROM dds.dim_country WHERE is_current = TRUE",
            conn,
        )


def apply_scd2_countries(engine, batch_id: uuid.UUID) -> int:
    """Compare NDS master against current DDS rows; expire changed rows and insert new versions."""
    today = date.today()
    yesterday = date.fromordinal(today.toordinal() - 1)

    with engine.connect() as conn:
        nds_countries = pd.read_sql(
            "SELECT iso3_code, country_name, region FROM nds.dim_country",
            conn,
        )

    dds_current = load_dds_countries(engine)
    dds_lookup = dds_current.set_index("country_bk") if not dds_current.empty else pd.DataFrame()

    rows_inserted = 0

    for _, nds_row in nds_countries.iterrows():
        bk = nds_row["iso3_code"]
        new_name   = nds_row["country_name"]
        new_region = nds_row.get("region")

        if not dds_lookup.empty and bk in dds_lookup.index:
            existing = dds_lookup.loc[bk]
            # SCD2: detect meaningful attribute change
            changed = (
                existing["country_name"] != new_name
                or existing.get("region") != new_region
            )
            if not changed:
                continue
            # Expire the old version
            with engine.begin() as conn:
                conn.execute(
                    text("""
                    UPDATE dds.dim_country
                    SET valid_to = :yesterday, is_current = FALSE
                    WHERE country_bk = :bk AND is_current = TRUE
                    """),
                    {"yesterday": yesterday, "bk": bk},
                )
            logger.info("SCD2 expire: country_bk=%s old_name='%s'", bk, existing["country_name"])

        # Insert new (or first) version
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO dds.dim_country
                    (country_bk, country_name, region, valid_from, valid_to, is_current, batch_id)
                VALUES
                    (:bk, :name, :region, :valid_from, '9999-12-31', TRUE, :batch_id::UUID)
                ON CONFLICT DO NOTHING
                """),
                {
                    "bk": bk, "name": new_name, "region": new_region,
                    "valid_from": today, "batch_id": str(batch_id),
                },
            )
        rows_inserted += 1

    logger.info("SCD2 dim_country: %d new/updated rows inserted.", rows_inserted)
    return rows_inserted


# ---------------------------------------------------------------------------
# SCD Type 1 — dds.dim_product
# ---------------------------------------------------------------------------

def apply_scd1_products(engine, batch_id: uuid.UUID) -> int:
    with engine.connect() as conn:
        nds_products = pd.read_sql(
            "SELECT hs_code, hs_chapter, description, hs_version FROM nds.dim_hs_product",
            conn,
        )

    if nds_products.empty:
        return 0

    rows = [
        {
            "product_bk":  r["hs_code"],
            "hs_chapter":  r["hs_chapter"],
            "description": r["description"],
            "hs_version":  r.get("hs_version", "HS2017"),
            "batch_id":    str(batch_id),
        }
        for _, r in nds_products.iterrows()
    ]

    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO dds.dim_product
                (product_bk, hs_chapter, description, hs_version, batch_id, updated_at)
            VALUES
                (:product_bk, :hs_chapter, :description, :hs_version, :batch_id::UUID, NOW())
            ON CONFLICT (product_bk, hs_version) DO UPDATE SET
                hs_chapter   = EXCLUDED.hs_chapter,
                description  = EXCLUDED.description,
                batch_id     = EXCLUDED.batch_id,
                updated_at   = NOW()
            """),
            rows,
        )
    logger.info("SCD1 dim_product: upserted %d rows.", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Fact load — dds.fact_trade
# ---------------------------------------------------------------------------

def load_fact_trade(engine, batch_id: uuid.UUID) -> int:
    """Resolve surrogate keys from current DDS dims and upsert into dds.fact_trade."""
    with engine.begin() as conn:
        result = conn.execute(text("""
        INSERT INTO dds.fact_trade (
            reporter_sk, partner_sk, product_sk, date_year_sk,
            trade_flow, trade_value_usd, quantity, quantity_unit,
            source_system, batch_id, updated_at
        )
        SELECT
            rep.country_sk,
            par.country_sk,
            dp.product_sk,
            -- Jan 1 of the report year as the date_sk (YYYYMMDD integer)
            (nf.period_year::TEXT || '0101')::INTEGER,
            nf.trade_flow,
            nf.trade_value_usd,
            nf.quantity,
            nf.quantity_unit,
            nf.source_system,
            :batch_id::UUID,
            NOW()
        FROM nds.fact_trade_flow nf
        JOIN dds.dim_country rep ON rep.country_bk = (
            SELECT iso3_code FROM nds.dim_country WHERE country_id = nf.reporter_id
        ) AND rep.is_current
        JOIN dds.dim_country par ON par.country_bk = (
            SELECT iso3_code FROM nds.dim_country WHERE country_id = nf.partner_id
        ) AND par.is_current
        JOIN dds.dim_product dp ON dp.product_bk = (
            SELECT hs_code FROM nds.dim_hs_product WHERE product_id = nf.product_id
        )
        -- Only load rows where the date_sk actually exists in dim_date
        JOIN dds.dim_date dd ON dd.date_sk = (nf.period_year::TEXT || '0101')::INTEGER
        ON CONFLICT (reporter_sk, partner_sk, product_sk, date_year_sk, trade_flow, source_system)
        DO UPDATE SET
            trade_value_usd = EXCLUDED.trade_value_usd,
            quantity        = EXCLUDED.quantity,
            quantity_unit   = EXCLUDED.quantity_unit,
            batch_id        = EXCLUDED.batch_id,
            updated_at      = NOW()
        """), {"batch_id": str(batch_id)})
    logger.info("dds.fact_trade: upserted %d rows.", result.rowcount)
    return result.rowcount


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"nds_to_dds_scd_{datetime.now(timezone.utc).date()}")

    try:
        apply_scd2_countries(engine, batch_id)
        apply_scd1_products(engine, batch_id)
        rows = load_fact_trade(engine, batch_id)

        if managed_batch:
            complete_batch(engine, batch_id, rows_loaded=rows)
    except Exception as exc:
        logger.exception("nds_to_dds_scd failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise


if __name__ == "__main__":
    run()
