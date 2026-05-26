"""
Phase 01 — Extract from static raw files (CSV / Excel).

Reads UN Comtrade and GSO trade files from the mounted raw_data directory
(or downloads them from the VPS1 file endpoint) and loads them into the
corresponding stg.* staging tables.

Supported file types: .csv, .xlsx
"""

from __future__ import annotations

import sys
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, get_psycopg2_conn, register_batch, complete_batch

logger = get_logger(__name__)

# Map filename patterns to source system labels and target stg tables
FILE_ROUTING = {
    "un_comtrade": ("UN_COMTRADE_CSV", "stg.trade_flow_raw"),
    "gso_trade":   ("GSO_CSV",         "stg.gso_trade_raw"),
}

# UN Comtrade CSV → stg.trade_flow_raw column mapping (raw header → stg column)
COMTRADE_COLUMN_MAP = {
    "Reporter ISO":         "reporter_code",
    "Reporter":             "reporter_name",
    "Partner ISO":          "partner_code",
    "Partner":              "partner_name",
    "Commodity Code":       "hs_code",
    "Commodity":            "hs_description",
    "Year":                 "period_year",
    "Period Desc.":         "period_type",
    "Trade Flow":           "trade_flow",
    "Trade Value (US$)":    "trade_value_usd",
    "Qty":                  "quantity",
    "Qty Unit":             "quantity_unit",
}

# GSO CSV → stg.gso_trade_raw column mapping
GSO_COLUMN_MAP = {
    "source_system":        "source_system",
    "report_year":          "report_year",
    "period_type":          "period_type",
    "reporter_code":        "reporter_code",
    "reporter_name":        "reporter_name",
    "partner_code":         "partner_code",
    "partner_name":         "partner_name",
    "hs_code":              "hs_code",
    "hs_description":       "hs_description",
    "trade_flow":           "trade_flow",
    "trade_value_vnd_billion": "trade_value_vnd",
    "trade_value_usd_million": "trade_value_usd",
    "quantity":             "quantity",
    "quantity_unit":        "quantity_unit",
    "data_quality_flag":    "data_quality_flag",
}


def read_file(filepath: Path) -> pd.DataFrame:
    suffix = filepath.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(filepath, dtype=str, keep_default_na=False)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(filepath, dtype=str, keep_default_na=False)
    raise ValueError(f"Unsupported file type: {suffix}")


def route_file(filepath: Path) -> tuple[str, str] | None:
    """Return (source_system, target_table) based on filename pattern, or None to skip."""
    name = filepath.stem.lower()
    for key, routing in FILE_ROUTING.items():
        if key in name:
            return routing
    logger.warning("No routing rule for file '%s' — skipping.", filepath.name)
    return None


def load_comtrade_df(
    conn: psycopg2.extensions.connection,
    df: pd.DataFrame,
    filepath: Path,
    batch_id: uuid.UUID,
) -> int:
    df = df.rename(columns=COMTRADE_COLUMN_MAP)
    required = list(COMTRADE_COLUMN_MAP.values())
    for col in required:
        if col not in df.columns:
            df[col] = None

    rows = [
        (
            row.get("reporter_code"), row.get("reporter_name"),
            row.get("partner_code"),  row.get("partner_name"),
            row.get("hs_code"),       row.get("hs_description"),
            row.get("period_year"),   row.get("period_type"),
            row.get("trade_flow"),    row.get("trade_value_usd"),
            row.get("quantity"),      row.get("quantity_unit"),
            "UN_COMTRADE_CSV",        str(filepath),
            str(batch_id),
        )
        for row in df.to_dict("records")
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
    return len(rows)


def load_gso_df(
    conn: psycopg2.extensions.connection,
    df: pd.DataFrame,
    filepath: Path,
    batch_id: uuid.UUID,
) -> int:
    df = df.rename(columns=GSO_COLUMN_MAP)
    required_cols = [
        "report_year", "period_type", "reporter_code", "reporter_name",
        "partner_code", "partner_name", "hs_code", "hs_description",
        "trade_flow", "trade_value_vnd", "trade_value_usd",
        "quantity", "quantity_unit", "data_quality_flag",
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    rows = [
        (
            row.get("report_year"),   row.get("period_type"),
            row.get("reporter_code"), row.get("reporter_name"),
            row.get("partner_code"),  row.get("partner_name"),
            row.get("hs_code"),       row.get("hs_description"),
            row.get("trade_flow"),    row.get("trade_value_vnd"),
            row.get("trade_value_usd"), row.get("quantity"),
            row.get("quantity_unit"), row.get("data_quality_flag"),
            str(filepath), str(batch_id),
        )
        for row in df.to_dict("records")
    ]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO stg.gso_trade_raw (
                report_year, period_type, reporter_code, reporter_name,
                partner_code, partner_name, hs_code, hs_description,
                trade_flow, trade_value_vnd, trade_value_usd,
                quantity, quantity_unit, data_quality_flag,
                source_file, batch_id
            ) VALUES %s
            """,
            rows,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, f"extract_raw_files_{datetime.now(timezone.utc).date()}")

    raw_dir = Path(cfg.raw_data_path)
    if not raw_dir.exists():
        logger.warning("raw_data_path '%s' does not exist — skipping file extraction.", raw_dir)
        return 0

    total_rows = 0
    try:
        for filepath in sorted(raw_dir.iterdir()):
            if filepath.suffix.lower() not in (".csv", ".xlsx", ".xls"):
                continue
            routing = route_file(filepath)
            if routing is None:
                continue

            source_system, _target_table = routing
            logger.info("Processing file: %s (source=%s)", filepath.name, source_system)

            df = read_file(filepath)
            logger.info("  Read %d rows from %s.", len(df), filepath.name)

            with get_psycopg2_conn(cfg) as conn:
                if source_system == "GSO_CSV":
                    n = load_gso_df(conn, df, filepath, batch_id)
                else:
                    n = load_comtrade_df(conn, df, filepath, batch_id)
            total_rows += n
            logger.info("  Loaded %d rows from %s.", n, filepath.name)

        if managed_batch:
            complete_batch(engine, batch_id, rows_extracted=total_rows, rows_loaded=total_rows)
    except Exception as exc:
        logger.exception("Raw file extraction failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    return total_rows


if __name__ == "__main__":
    run()
