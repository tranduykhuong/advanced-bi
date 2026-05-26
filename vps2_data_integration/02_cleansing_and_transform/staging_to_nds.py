"""
Phase 02b — ODS → NDS (Normalized Data Store, 3NF)

Promotes data from ods.* into the normalized nds.* schema:
  1. Reconciles country names with fuzzy matching (rapidfuzz) against the
     master nds.dim_country table — handles variant spellings from different
     source systems (e.g. "Korea, Rep." vs "Korea Republic" vs "South Korea").
  2. Upserts HS product master data into nds.dim_hs_product.
  3. Resolves foreign keys and upserts nds.fact_trade_flow.
"""

from __future__ import annotations

import sys
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rapidfuzz import process as fz_process, fuzz
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

FUZZY_THRESHOLD = 80  # Minimum score (0–100) to accept a fuzzy country match


# ---------------------------------------------------------------------------
# Country reconciliation
# ---------------------------------------------------------------------------

def load_known_countries(engine) -> pd.DataFrame:
    """Load existing nds.dim_country rows for fuzzy matching."""
    with engine.connect() as conn:
        return pd.read_sql(
            "SELECT country_id, iso3_code, country_name FROM nds.dim_country",
            conn,
        )


def reconcile_country(name: str, known_df: pd.DataFrame) -> tuple[str | None, float]:
    """Return (iso3_code, score) for the best fuzzy match, or (None, 0)."""
    if known_df.empty:
        return None, 0.0
    choices = known_df["country_name"].tolist()
    match = fz_process.extractOne(name, choices, scorer=fuzz.WRatio)
    if match and match[1] >= FUZZY_THRESHOLD:
        iso3 = known_df.loc[known_df["country_name"] == match[0], "iso3_code"].iloc[0]
        return iso3, match[1]
    return None, 0.0


def upsert_countries(engine, batch_id: uuid.UUID) -> None:
    """Merge ods.country_ref into nds.dim_country with fuzzy name reconciliation."""
    with engine.connect() as conn:
        ods_countries = pd.read_sql(
            "SELECT DISTINCT iso3_code, iso2_code, country_name, region FROM ods.country_ref",
            conn,
        )

    if ods_countries.empty:
        logger.info("No countries in ODS to reconcile.")
        return

    known = load_known_countries(engine)

    rows = []
    for _, row in ods_countries.iterrows():
        # Prefer exact ISO-3 match; fall back to fuzzy name match
        iso3 = row["iso3_code"].strip().upper() if pd.notna(row["iso3_code"]) else None
        name = row["country_name"].strip() if pd.notna(row["country_name"]) else ""

        match_score = 100.0
        if iso3 not in (known["iso3_code"].tolist() if not known.empty else []):
            _, match_score = reconcile_country(name, known)

        rows.append({
            "iso3_code":     iso3,
            "iso2_code":     row.get("iso2_code", "")[:2] if pd.notna(row.get("iso2_code")) else None,
            "country_name":  name,
            "region":        row.get("region"),
            "match_score":   round(match_score, 2),
            "is_reconciled": match_score >= FUZZY_THRESHOLD,
            "batch_id":      str(batch_id),
        })

    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO nds.dim_country
                (iso3_code, iso2_code, country_name, region, match_score, is_reconciled, updated_at)
            VALUES
                (:iso3_code, :iso2_code, :country_name, :region, :match_score, :is_reconciled, NOW())
            ON CONFLICT (iso3_code) DO UPDATE SET
                iso2_code     = EXCLUDED.iso2_code,
                country_name  = EXCLUDED.country_name,
                region        = EXCLUDED.region,
                match_score   = EXCLUDED.match_score,
                is_reconciled = EXCLUDED.is_reconciled,
                updated_at    = NOW()
            """),
            rows,
        )
    logger.info("Upserted %d country rows into nds.dim_country.", len(rows))


def upsert_products(engine, batch_id: uuid.UUID) -> None:
    with engine.connect() as conn:
        ods_products = pd.read_sql(
            "SELECT DISTINCT hs_code, hs_chapter, description, hs_version FROM ods.hs_product_ref",
            conn,
        )

    if ods_products.empty:
        return

    rows = [
        {
            "hs_code":    r["hs_code"].strip(),
            "hs_chapter": r["hs_chapter"].strip()[:2],
            "description": r["description"].strip(),
            "hs_version": r.get("hs_version", "HS2017") or "HS2017",
        }
        for _, r in ods_products.iterrows()
    ]

    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO nds.dim_hs_product (hs_code, hs_chapter, description, hs_version, updated_at)
            VALUES (:hs_code, :hs_chapter, :description, :hs_version, NOW())
            ON CONFLICT (hs_code, hs_version) DO UPDATE SET
                hs_chapter   = EXCLUDED.hs_chapter,
                description  = EXCLUDED.description,
                updated_at   = NOW()
            """),
            rows,
        )
    logger.info("Upserted %d HS product rows into nds.dim_hs_product.", len(rows))


def upsert_trade_facts(engine, batch_id: uuid.UUID) -> int:
    """Resolve ODS trade flows to NDS FKs and upsert into nds.fact_trade_flow."""
    with engine.begin() as conn:
        result = conn.execute(text("""
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
            o.is_late_arriving
        FROM ods.trade_flow o
        JOIN nds.dim_country rc ON rc.iso3_code = o.reporter_code
        JOIN nds.dim_country pc ON pc.iso3_code = o.partner_code
        JOIN nds.dim_hs_product pr ON pr.hs_code = o.hs_code
        ON CONFLICT (reporter_id, partner_id, product_id, period_year, trade_flow, source_system)
        DO UPDATE SET
            trade_value_usd  = EXCLUDED.trade_value_usd,
            quantity         = EXCLUDED.quantity,
            quantity_unit    = EXCLUDED.quantity_unit,
            batch_id         = EXCLUDED.batch_id,
            is_late_arriving = EXCLUDED.is_late_arriving,
            created_at       = nds.fact_trade_flow.created_at
        """), {"batch_id": str(batch_id)})
    logger.info("Upserted %d rows into nds.fact_trade_flow.", result.rowcount)
    return result.rowcount


def run(batch_id: uuid.UUID | None = None) -> None:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"staging_to_nds_{datetime.now(timezone.utc).date()}")

    try:
        upsert_countries(engine, batch_id)
        upsert_products(engine, batch_id)
        rows = upsert_trade_facts(engine, batch_id)
        if managed_batch:
            complete_batch(engine, batch_id, rows_loaded=rows)
    except Exception as exc:
        logger.exception("staging_to_nds failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise


if __name__ == "__main__":
    run()
