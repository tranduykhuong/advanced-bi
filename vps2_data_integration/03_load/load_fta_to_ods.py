"""Load transformed FTA records into ods.fta (SCD Type 1 UPSERT on aptiad_no)."""

from __future__ import annotations

import ast
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

from importlib import import_module

_fta_transform = import_module("02_transform.fta_stage_to_ods")
EXPECTED_COLS = _fta_transform.EXPECTED_COLS

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.fta (
    fta_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aptiad_no INTEGER NOT NULL,
    fta_name VARCHAR(300),
    member_countries TEXT[],
    status VARCHAR(80),
    scope VARCHAR(80),
    agreement_type VARCHAR(120),
    is_upgraded BOOLEAN,
    upgraded_status VARCHAR(120),
    year_signature_upgraded INTEGER,
    year_enforcement_upgraded INTEGER,
    has_trade_goods BOOLEAN,
    year_signature_goods INTEGER,
    year_enforcement_goods INTEGER,
    wto_notification_goods TEXT,
    wto_notification_link TEXT,
    wto_notification_year_goods INTEGER,
    wto_consideration_goods TEXT,
    has_trade_services BOOLEAN,
    year_signature_services INTEGER,
    year_enforcement_services INTEGER,
    wto_notification_services TEXT,
    wto_notification_year_services INTEGER,
    wto_consideration_services TEXT,
    liberalization_services TEXT,
    has_investment BOOLEAN,
    year_signature_investment INTEGER,
    year_enforcement_investment INTEGER,
    liberalization_investment TEXT,
    bit_unctad TEXT,
    provision_sps_tbt BOOLEAN,
    provision_anti_dumping BOOLEAN,
    provision_safeguard BOOLEAN,
    provision_trade_facilitation BOOLEAN,
    provision_gov_procurement BOOLEAN,
    provision_competition_policy BOOLEAN,
    provision_intellectual_property BOOLEAN,
    provision_dispute_settlement BOOLEAN,
    provision_movement_natural_persons BOOLEAN,
    provision_sd_related BOOLEAN,
    provision_sd_by_concept BOOLEAN,
    provision_labour BOOLEAN,
    provision_human_rights BOOLEAN,
    provision_gender BOOLEAN,
    provision_health BOOLEAN,
    provision_environment BOOLEAN,
    provision_smes BOOLEAN,
    provision_technical_cooperation BOOLEAN,
    provision_transparency BOOLEAN,
    provision_financial_services BOOLEAN,
    provision_telecommunications BOOLEAN,
    provision_ecommerce BOOLEAN,
    provision_ecommerce_consumer_protection BOOLEAN,
    provision_ecommerce_personal_data BOOLEAN,
    provision_ecommerce_data_flows BOOLEAN,
    source_link TEXT,
    source_system VARCHAR(50) NOT NULL DEFAULT 'APTIAD',
    snapshot_date DATE,
    batch_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_ods_fta_aptiad_no UNIQUE (aptiad_no)
);
"""


def _parse_member_countries(val) -> list[str]:
    if isinstance(val, list):
        return val
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return []
    text_val = str(val).strip()
    if not text_val:
        return []
    try:
        parsed = ast.literal_eval(text_val)
        if isinstance(parsed, list):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return [text_val]


def _record_value(val):
    if val is None:
        return None
    if isinstance(val, list):
        return val
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, bool):
        return val
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        if pd.isna(val):
            return None
        if float(val).is_integer():
            return int(val)
        return float(val)
    if isinstance(val, uuid.UUID):
        return val
    return val


def _prepare_for_db(df: pd.DataFrame, batch_id: uuid.UUID) -> pd.DataFrame:
    df = df.copy()

    df["aptiad_no"] = pd.to_numeric(df["aptiad_no"], errors="coerce")

    int_cols = [
        "aptiad_no",
        "year_signature_upgraded",
        "year_enforcement_upgraded",
        "year_signature_goods",
        "year_enforcement_goods",
        "wto_notification_year_goods",
        "year_signature_services",
        "year_enforcement_services",
        "wto_notification_year_services",
        "year_signature_investment",
        "year_enforcement_investment",
    ]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    bool_cols = [
        "is_upgraded",
        "has_trade_goods",
        "has_trade_services",
        "has_investment",
    ] + [c for c in EXPECTED_COLS if c.startswith("provision_")]

    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(
                lambda x: None if pd.isna(x) or x == "" else bool(x)
            )

    if "member_countries" in df.columns:
        df["member_countries"] = df["member_countries"].apply(_parse_member_countries)

    if "batch_id" in df.columns:
        df["batch_id"] = df["batch_id"].apply(
            lambda x: batch_id if pd.isna(x) or str(x).strip() == "" else uuid.UUID(str(x))
        )
    else:
        df["batch_id"] = batch_id

    return df


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_fta_to_ods")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "fta_stage_to_ods_transformed.csv"
        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        df = pd.read_csv(input_file, low_memory=False, keep_default_na=False)
        for col in EXPECTED_COLS:
            if col not in df.columns:
                df[col] = None
        df = df[EXPECTED_COLS]
        df = _prepare_for_db(df, batch_id)

        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))

        insert_cols = EXPECTED_COLS
        update_cols = [c for c in insert_cols if c not in ("aptiad_no", "source_system")]

        records = [
            tuple(_record_value(row[c]) for c in insert_cols) for _, row in df.iterrows()
        ]

        upsert_query = f"""
            INSERT INTO ods.fta ({", ".join(insert_cols)})
            VALUES %s
            ON CONFLICT (aptiad_no) DO UPDATE SET
                {", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)},
                updated_at = NOW()
        """

        with engine.begin() as conn:
            raw_conn = conn.connection
            cursor = raw_conn.cursor()
            execute_values(cursor, upsert_query, records, page_size=500)
            raw_conn.commit()

        logger.info("Upserted %s rows into ods.fta", len(df))

    except Exception as exc:
        logger.exception("load_fta_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))

    return len(df)


if __name__ == "__main__":
    run()
