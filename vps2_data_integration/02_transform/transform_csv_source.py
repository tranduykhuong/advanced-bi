"""
Transform extracted UN Comtrade CSV data before loading into staging.

Responsibilities:
  - Rename columns from UN Comtrade camelCase to snake_case (staging DDL naming)
  - Cast numeric columns to float (source CSV may encode values as bool/string)
  - Read from tmp/trade_extracted.csv, write to tmp/trade_transformed.csv

Entry point:
  run() -> pd.DataFrame
    Returns the transformed DataFrame. Saves result to tmp/trade_transformed.csv.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

COLUMN_RENAME_MAP = {
    "cmdCode": "cmd_code",
    "cmdDesc": "cmd_desc",
    "reporterISO": "reporter_iso",
    "reporterDesc": "reporter_desc",
    "partnerISO": "partner_iso",
    "partnerDesc": "partner_desc",
    "flowCode": "flow_code",
    "flowDesc": "flow_desc",
    "primaryValue": "primary_value",
    "cifvalue": "cif_value",
    "fobvalue": "fob_value",
    "netWgt": "net_wgt",
    "qtyUnitAbbr": "qty_unit",
    "motCode": "mot_code",
    "motDesc": "mot_desc",
}

NUMERIC_COLUMNS = ("primary_value", "cif_value", "fob_value", "net_wgt", "qty")


def run(batch_id: uuid.UUID | None = None) -> pd.DataFrame:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None

    if managed_batch:
        batch_id = register_batch(engine, "transform_csv_source")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "trade_extracted.csv"
        output_file = tmp_dir / "trade_transformed.csv"

        if not input_file.exists():
            logger.warning(
                "Extracted CSV file not found at %s — skipping.", input_file
            )
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return pd.DataFrame()

        df = pd.read_csv(input_file, dtype=str)

        df = df.rename(columns=COLUMN_RENAME_MAP)

        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df.to_csv(output_file, index=False)

        rows_processed = len(df)

        logger.info("Transformed %s rows → %s", rows_processed, output_file)

    except Exception as exc:
        logger.exception("transform_csv_source failed: %s", exc)

        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))

        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_processed)

    return df


if __name__ == "__main__":
    df = run()
    print(f"Transformed {len(df)} rows → tmp/trade_transformed.csv")
