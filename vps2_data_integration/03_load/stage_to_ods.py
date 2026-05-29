from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


EXPECTED_COLS = [
    "year",
    "quarter",
    "month",
    "hs_code",
    "category_chapter",
    "category_heading",
    "product_name",
    "partner_code",
    "partner_name",
    "partner_region",
    "partner_continent",
    "fta_keys",
    "flow_type",
    "value",
    "quantity",
    "unit",
    "record_source",
    "source_system",
    "batch_id",
    "is_late_arriving",
    "quality_flags",
]


TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.trade_transaction (
    ods_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    year                INTEGER NOT NULL,
    quarter             SMALLINT,
    month               SMALLINT NOT NULL,
    hs_code             VARCHAR(8),
    category_chapter    TEXT,
    category_heading    TEXT,
    product_name        TEXT,
    partner_code        VARCHAR(3),
    partner_name        TEXT,
    partner_region      TEXT,
    partner_continent   TEXT,
    fta_keys            INT[],
    flow_type           BOOLEAN NOT NULL,
    value               NUMERIC(18,6),
    quantity            NUMERIC(18,6),
    unit                VARCHAR(20),
    record_source       VARCHAR(20),

    source_system       VARCHAR(50) NOT NULL,
    batch_id            UUID NOT NULL,
    is_late_arriving    BOOLEAN DEFAULT FALSE,
    quality_flags       TEXT[],
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_trade_transaction
        UNIQUE (year, month, hs_code, partner_code, flow_type, record_source)
);
"""


UPSERT_QUERY = """
    INSERT INTO ods.trade_transaction (
        year, quarter, month, hs_code, category_chapter, category_heading, product_name,
        partner_code, partner_name, partner_region, partner_continent, fta_keys,
        flow_type, value, quantity, unit, record_source, source_system,
        batch_id, is_late_arriving, quality_flags
    ) VALUES %s
    ON CONFLICT ON CONSTRAINT uq_ods_trade_transaction
    DO UPDATE SET
        -- Accumulate numerics; revert to absolute value on same-batch reload
        value            = CASE
                               WHEN excluded.batch_id = ods.trade_transaction.batch_id
                               THEN excluded.value
                               ELSE COALESCE(ods.trade_transaction.value,    0)
                                  + COALESCE(excluded.value,                 0)
                           END,
        quantity         = CASE
                               WHEN excluded.batch_id = ods.trade_transaction.batch_id
                               THEN excluded.quantity
                               ELSE COALESCE(ods.trade_transaction.quantity, 0)
                                  + COALESCE(excluded.quantity,              0)
                           END,

        -- Non-key descriptive fields: always overwrite with latest value
        quarter          = excluded.quarter,
        category_chapter = excluded.category_chapter,
        category_heading = excluded.category_heading,
        product_name     = excluded.product_name,
        partner_name     = excluded.partner_name,
        partner_region   = excluded.partner_region,
        partner_continent= excluded.partner_continent,
        fta_keys         = excluded.fta_keys,
        unit             = excluded.unit,
        source_system    = excluded.source_system,
        batch_id         = excluded.batch_id,
        is_late_arriving = excluded.is_late_arriving,
        quality_flags    = excluded.quality_flags,
        updated_at       = NOW()
"""


def _prepare_for_db(df: pd.DataFrame, batch_id: uuid.UUID) -> pd.DataFrame:
    df = df.copy()

    # Boolean
    for col in ["is_late_arriving"]:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)

    # Array
    for col in ["quality_flags", "fta_keys"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

    # Numeric
    for col in ["year", "quarter", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    for col in ["value", "quantity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # batch_id normalization
    if "batch_id" in df.columns:
        df["batch_id"] = df["batch_id"].apply(
            lambda x: (
                batch_id if pd.isna(x) or str(x).strip() == "" else uuid.UUID(str(x))
            )
        )

    return df


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_to_ods")

    try:
        input_file = Path("/app/tmp/stage_to_ods_transformed.csv")
        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        df = pd.read_csv(
            input_file,
            low_memory=False,
            dtype={
                "hs_code": str,
                "category_chapter": str,
                "category_heading": str,
                "partner_code": str,
                "unit": str,
                "record_source": str,
                "source_system": str,
                "partner_name": str,
                "product_name": str,
                "batch_id": str,
            },
            keep_default_na=False,
        )

        logger.info("Loaded %s rows", len(df))

        # Ensure full schema
        for c in EXPECTED_COLS:
            if c not in df.columns:
                df[c] = None

        df = df[EXPECTED_COLS]

        df = _prepare_for_db(df, batch_id)

        CONFLICT_KEYS = [
            "year",
            "month",
            "hs_code",
            "partner_code",
            "flow_type",
            "record_source",
        ]
        pre_dedup = len(df)

        agg: dict[str, str] = {}
        for col in df.columns:
            if col in CONFLICT_KEYS:
                continue
            elif col in ("value", "quantity"):
                agg[col] = "sum"
            else:
                agg[col] = "last"

        df = df.groupby(CONFLICT_KEYS, dropna=False).agg(agg).reset_index()

        dupes_removed = pre_dedup - len(df)
        if dupes_removed:
            logger.warning(
                "Removed %s duplicate rows within batch (same conflict key). "
                "Numeric columns were summed; all others kept last value.",
                dupes_removed,
            )

        # =========================
        # CREATE TABLE (if not exists)
        # =========================
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))

        # =========================
        # UPSERT
        # =========================
        records = [
            (
                row["year"],
                row["quarter"],
                row["month"],
                row["hs_code"],
                row["category_chapter"],
                row["category_heading"],
                row["product_name"],
                row["partner_code"],
                row["partner_name"],
                row["partner_region"],
                row["partner_continent"],
                row["fta_keys"],
                row["flow_type"],
                row["value"],
                row["quantity"],
                row["unit"],
                row["record_source"],
                row["source_system"],
                row["batch_id"],
                row["is_late_arriving"],
                row["quality_flags"],
            )
            for _, row in df.iterrows()
        ]

        with engine.begin() as conn:
            raw_conn = conn.connection
            cursor = raw_conn.cursor()

            logger.info("Upserting %s rows into ods.trade_transaction...", len(records))
            execute_values(cursor, UPSERT_QUERY, records, page_size=2000)

            raw_conn.commit()

        logger.info(
            "Upsert complete: %s rows processed into ods.trade_transaction", len(df)
        )

    except Exception as exc:
        logger.exception("load_stage_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))

    return len(df)


if __name__ == "__main__":
    run()
