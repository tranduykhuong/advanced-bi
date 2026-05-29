"""Load transformed APTIAD data into stage.stage_aptiad."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.aptiad_columns import STAGE_LOAD_COLUMNS
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

_transform = importlib.import_module("02_transform.transform_aptiad_source")

logger = get_logger(__name__)

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_aptiad (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aptiad_no INTEGER NOT NULL,
    title TEXT,
    members_raw TEXT,
    status TEXT,
    scope TEXT,
    agreement_type TEXT,
    upgraded TEXT,
    upgraded_status TEXT,
    year_signature_upgraded TEXT,
    year_enforcement_upgraded TEXT,
    trade_in_goods TEXT,
    year_signature_goods TEXT,
    year_enforcement_goods TEXT,
    wto_notification_goods TEXT,
    wto_notification_link_goods TEXT,
    wto_notification_year_goods TEXT,
    wto_consideration_goods TEXT,
    sps_tbt TEXT,
    anti_dumping_duty TEXT,
    safeguard TEXT,
    trade_in_services TEXT,
    year_signature_services TEXT,
    year_enforcement_services TEXT,
    wto_notification_services TEXT,
    wto_notification_year_services TEXT,
    wto_consideration_services TEXT,
    liberalization_services TEXT,
    investment TEXT,
    year_signature_investment TEXT,
    year_enforcement_investment TEXT,
    liberalization_investment TEXT,
    bit_unctad TEXT,
    trade_facilitation TEXT,
    gov_procurement TEXT,
    competition_policy TEXT,
    intellectual_property TEXT,
    dispute_settlement TEXT,
    movement_natural_persons TEXT,
    sd_related TEXT,
    sd_by_concept TEXT,
    labour TEXT,
    human_rights TEXT,
    gender TEXT,
    health TEXT,
    environment TEXT,
    smes TEXT,
    technical_cooperation TEXT,
    transparency TEXT,
    financial_services TEXT,
    telecommunications TEXT,
    ecommerce TEXT,
    ecommerce_consumer_protection TEXT,
    ecommerce_personal_data TEXT,
    ecommerce_data_flows TEXT,
    link_website TEXT,
    source_file TEXT,
    snapshot_date DATE,
    batch_id UUID,
    extracted_at TIMESTAMP DEFAULT NOW()
);
"""


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_stage_aptiad")

    rows_loaded = 0
    try:
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))
            logger.info("Table schema initialized")

        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE stage.stage_aptiad"))
            logger.info("Truncated stage.stage_aptiad")

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        extracted_file = tmp_dir / "aptiad_extracted.csv"

        if not extracted_file.exists():
            logger.warning("Extracted APTIAD file not found at %s", extracted_file)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        df = _transform.run(batch_id=batch_id)
        df["batch_id"] = str(batch_id)

        load_cols = [c for c in STAGE_LOAD_COLUMNS if c != "batch_id"]
        load_cols.append("batch_id")
        df = df[load_cols]

        df.to_sql(
            "stage_aptiad",
            engine,
            schema="stage",
            if_exists="append",
            index=False,
        )
        rows_loaded = len(df)
        logger.info("Loaded %d rows into stage.stage_aptiad", rows_loaded)

    except Exception as exc:
        logger.exception("load_stage_aptiad failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
