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
    "chapter_name",
    "heading_name",
    "product_name",
    "partner_code",
    "partner_name",
    "partner_region",
    "partner_continent",
    "flow_type",
    "value",
    "quantity",
    "unit",
    "source_system",
    "batch_id",
    "is_late_arriving",
]


TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.trade_transaction (
    ods_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    year                INTEGER NOT NULL,
    quarter             SMALLINT,
    month               SMALLINT NOT NULL,
    hs_code             VARCHAR(8),
    chapter_name    TEXT,
    heading_name    TEXT,
    product_name        TEXT,
    partner_code        VARCHAR(3),
    partner_name        TEXT,
    partner_region      TEXT,
    partner_continent   TEXT,
    flow_type           BOOLEAN NOT NULL,
    value               NUMERIC(18,6),
    quantity            NUMERIC(18,6),
    unit                VARCHAR(20),
    source_system       VARCHAR(20) NOT NULL,

    batch_id            UUID NOT NULL,
    is_late_arriving    BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_ods_trade_transaction
        UNIQUE (year, month, hs_code, partner_code, flow_type, source_system)
);
"""


UPSERT_QUERY = """
    INSERT INTO ods.trade_transaction (
        year, quarter, month, hs_code, chapter_name, heading_name, product_name,
        partner_code, partner_name, partner_region, partner_continent,
        flow_type, value, quantity, unit, source_system,
        batch_id, is_late_arriving
    ) VALUES %s
    ON CONFLICT ON CONSTRAINT uq_ods_trade_transaction
    DO UPDATE SET
        -- Accumulate numerics; revert to absolute value on same-batch reload
        value            = CASE
                               WHEN excluded.batch_id = ods.trade_transaction.batch_id
                               THEN COALESCE(ods.trade_transaction.value,    0)
                                  + COALESCE(excluded.value,                 0)
                               ELSE excluded.value
                           END,
        quantity         = CASE
                               WHEN excluded.batch_id = ods.trade_transaction.batch_id
                               THEN COALESCE(ods.trade_transaction.quantity, 0)
                                  + COALESCE(excluded.quantity,              0)
                               ELSE excluded.quantity
                           END,

        -- Non-key descriptive fields: always overwrite with latest value
        quarter          = excluded.quarter,
        chapter_name = excluded.chapter_name,
        heading_name = excluded.heading_name,
        product_name     = excluded.product_name,
        partner_name     = excluded.partner_name,
        partner_region   = excluded.partner_region,
        partner_continent= excluded.partner_continent,
        unit             = excluded.unit,
        batch_id         = excluded.batch_id,
        is_late_arriving = excluded.is_late_arriving,
        updated_at       = NOW()
"""


_SQL_ADVANCE_WATERMARK = text("""
    INSERT INTO ods.etl_watermark (source_system, max_period_year, max_period_month, last_updated)
    VALUES (:source, :yr, :mo, NOW())
    ON CONFLICT (source_system) DO UPDATE SET
        max_period_year  = CASE
            WHEN EXCLUDED.max_period_year * 100 + EXCLUDED.max_period_month
                 > COALESCE(ods.etl_watermark.max_period_year, 0) * 100
                   + COALESCE(ods.etl_watermark.max_period_month, 0)
            THEN EXCLUDED.max_period_year
            ELSE ods.etl_watermark.max_period_year
        END,
        max_period_month = CASE
            WHEN EXCLUDED.max_period_year * 100 + EXCLUDED.max_period_month
                 > COALESCE(ods.etl_watermark.max_period_year, 0) * 100
                   + COALESCE(ods.etl_watermark.max_period_month, 0)
            THEN EXCLUDED.max_period_month
            ELSE ods.etl_watermark.max_period_month
        END,
        last_updated = NOW()
""")


def _advance_watermarks(engine, df: pd.DataFrame) -> None:
    """Advance ods.etl_watermark per source_system to MAX(year, month) loaded
    in this batch, so the next run's late-arriving detection (stage_to_ods.py)
    has an up-to-date baseline to compare against.
    """
    if df.empty or "source_system" not in df.columns:
        return

    tmp = df.dropna(subset=["source_system", "year", "month"]).copy()
    if tmp.empty:
        return

    tmp["period"] = tmp["year"].astype(int) * 100 + tmp["month"].astype(int)

    with engine.begin() as conn:
        for source_system, grp in tmp.groupby("source_system"):
            max_period = int(grp["period"].max())
            year, month = divmod(max_period, 100)
            conn.execute(
                _SQL_ADVANCE_WATERMARK,
                {"source": str(source_system), "yr": year, "mo": month},
            )

    logger.info(
        "Advanced ods.etl_watermark for source_system(s): %s",
        sorted(tmp["source_system"].unique().tolist()),
    )


def _prepare_for_db(df: pd.DataFrame, batch_id: uuid.UUID) -> pd.DataFrame:
    df = df.copy()

    # Boolean
    for col in ["is_late_arriving"]:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)

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
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "stage_to_ods_transformed.csv"
        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        df = pd.read_csv(
            input_file,
            low_memory=False,
            dtype={
                "hs_code": str,
                "chapter_name": str,
                "heading_name": str,
                "partner_code": str,
                "unit": str,
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
            "source_system",
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

        # Not a rejection: rows sharing a conflict key within this batch are
        # legitimately aggregated (numeric columns summed) to match the ODS
        # grain — no data is dropped, so this does not go to reject_records.
        # Kept as an operational log line only.
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
                row["chapter_name"],
                row["heading_name"],
                row["product_name"],
                row["partner_code"],
                row["partner_name"],
                row["partner_region"],
                row["partner_continent"],
                row["flow_type"],
                row["value"],
                row["quantity"],
                row["unit"],
                row["source_system"],
                row["batch_id"],
                row["is_late_arriving"],
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

        _advance_watermarks(engine, df)

    except Exception as exc:
        logger.exception("load_stage_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df), rows_upserted=len(df))

    return len(df)


if __name__ == "__main__":
    run()
