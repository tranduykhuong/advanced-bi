"""
Phase 01 — Extract from TradeMap mock API (VPS1).

Pulls paginated trade flow records and metadata from the mock API and bulk
inserts them into stg.trade_flow_raw and stg.country_ref_raw / stg.hs_product_ref_raw.

The staging tables are TRUNCATED at the start of each run (idempotent reload).
"""

from __future__ import annotations

import sys
import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg2.extras

# Allow imports from parent package when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, get_psycopg2_conn, register_batch, complete_batch

logger = get_logger(__name__)

PAGE_SIZE = 500
SOURCE_SYSTEM = "TRADEMAP_API"


def truncate_staging(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE stg.trade_flow_raw RESTART IDENTITY")
        cur.execute("TRUNCATE TABLE stg.country_ref_raw RESTART IDENTITY")
        cur.execute("TRUNCATE TABLE stg.hs_product_ref_raw RESTART IDENTITY")
    conn.commit()
    logger.info("Staging tables truncated.")


def fetch_all_flows(api_url: str) -> list[dict]:
    """Paginate through /api/trade/flows until all records are fetched."""
    records: list[dict] = []
    page = 1
    with httpx.Client(base_url=api_url, timeout=30) as client:
        while True:
            resp = client.get(
                "/api/trade/flows",
                params={"page": page, "page_size": PAGE_SIZE},
            )
            resp.raise_for_status()
            payload = resp.json()
            batch = payload["data"]
            records.extend(batch)
            logger.info("Fetched page %d — %d records (total so far: %d)", page, len(batch), len(records))
            if len(records) >= payload["total_records"] or not batch:
                break
            page += 1
    return records


def fetch_metadata(api_url: str) -> dict:
    with httpx.Client(base_url=api_url, timeout=30) as client:
        resp = client.get("/api/trade/metadata")
        resp.raise_for_status()
        return resp.json()


def insert_trade_flows(
    conn: psycopg2.extensions.connection,
    records: list[dict],
    batch_id: uuid.UUID,
) -> int:
    rows = [
        (
            r["reporter_code"],
            r["reporter_name"],
            r["partner_code"],
            r["partner_name"],
            r["hs_code"],
            r["hs_description"],
            str(r["period_year"]),
            "Annual",
            r["trade_flow"],
            str(r["trade_value_usd"]) if r.get("trade_value_usd") is not None else None,
            str(r["quantity"])       if r.get("quantity")       is not None else None,
            r.get("quantity_unit"),
            SOURCE_SYSTEM,
            "/api/trade/flows",
            str(batch_id),
        )
        for r in records
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO stg.trade_flow_raw (
                reporter_code, reporter_name, partner_code, partner_name,
                hs_code, hs_description, period_year, period_type, trade_flow,
                trade_value_usd, quantity, quantity_unit,
                source_system, source_file, batch_id
            ) VALUES %s
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    logger.info("Inserted %d rows into stg.trade_flow_raw.", len(rows))
    return len(rows)


def insert_metadata(
    conn: psycopg2.extensions.connection,
    metadata: dict,
    batch_id: uuid.UUID,
) -> None:
    country_rows = [
        (
            c["iso3_code"], c["iso2_code"], c["country_name"],
            c.get("region"), SOURCE_SYSTEM, str(batch_id),
        )
        for c in metadata.get("countries", [])
    ]
    hs_rows = [
        (
            h["hs_code"], h["hs_chapter"], h["description"],
            h.get("hs_version", "HS2017"), SOURCE_SYSTEM, str(batch_id),
        )
        for h in metadata.get("hs_products", [])
    ]

    with conn.cursor() as cur:
        if country_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO stg.country_ref_raw
                    (iso3_code, iso2_code, country_name, region, source_system, batch_id)
                VALUES %s
                """,
                country_rows,
            )
        if hs_rows:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO stg.hs_product_ref_raw
                    (hs_code, hs_chapter, description, hs_version, source_system, batch_id)
                VALUES %s
                """,
                hs_rows,
            )
    conn.commit()
    logger.info(
        "Inserted %d countries and %d HS products into staging ref tables.",
        len(country_rows), len(hs_rows),
    )


def run(batch_id: uuid.UUID | None = None) -> int:
    """Entry point. Returns number of rows loaded into stg.trade_flow_raw."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"extract_trademap_api_{datetime.now(timezone.utc).date()}")

    rows_loaded = 0
    try:
        with get_psycopg2_conn(cfg) as conn:
            truncate_staging(conn)

            logger.info("Fetching metadata from %s ...", cfg.vps1_api_url)
            metadata = fetch_metadata(cfg.vps1_api_url)
            insert_metadata(conn, metadata, batch_id)

            logger.info("Fetching trade flows from %s ...", cfg.vps1_api_url)
            records = fetch_all_flows(cfg.vps1_api_url)
            rows_loaded = insert_trade_flows(conn, records, batch_id)

        if managed_batch:
            complete_batch(engine, batch_id, rows_extracted=len(records), rows_loaded=rows_loaded)
    except Exception as exc:
        logger.exception("Extract from TradeMap API failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    return rows_loaded


if __name__ == "__main__":
    run()
