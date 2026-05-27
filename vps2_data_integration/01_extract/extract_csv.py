"""
Extract trade data from CSV sources (UN Comtrade format).

Key columns extracted:
    - period, cmdCode, cmdDesc, reporterISO, partnerISO, partnerDesc
    - flowCode, flowDesc, primaryValue, cifValue, fobValue
    - netWgt, qty, qtyUnit, motCode, motDesc
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

# Columns to extract from CSV
REQUIRED_COLUMNS = [
    "period",
    "cmdCode",
    "cmdDesc",
    "reporterISO",
    "partnerISO",
    "partnerDesc",
    "flowCode",
    "flowDesc",
    "primaryValue",
    "cifvalue",
    "fobvalue",
    "netWgt",
    "qty",
    "qtyUnitAbbr",
    "motCode",
    "motDesc",
]


def run(batch_id: uuid.UUID | None = None) -> int:
    """Extract CSV data from raw_data/csv_source directory."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_csv")

    total_rows = 0
    try:
        csv_dir = Path(cfg.raw_data_path) / "csv_source"
        
        if not csv_dir.exists():
            logger.warning("CSV_SOURCE_PATH '%s' not found — skipping.", csv_dir)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        # Create tmp directory for extracted data
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "trade_extracted.csv"

        # Process each CSV file
        all_dfs = []
        for csv_file in sorted(csv_dir.glob("*.csv")):
            logger.info("Extracting CSV file: %s", csv_file.name)
            
            # Read CSV and select required columns
            df = pd.read_csv(csv_file, usecols=REQUIRED_COLUMNS, low_memory=False, encoding="latin-1", index_col=False)
            
            logger.info("  → Loaded %d rows from %s", len(df), csv_file.name)
            
            # Data validation/cleaning could be added here
            # df = df.dropna(subset=["period", "cmdCode"])
            
            all_dfs.append(df)
            total_rows += len(df)

        # Concatenate and save to temp file
        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            combined_df.to_csv(output_file, index=False)
            logger.info("Saved %d extracted rows to %s", total_rows, output_file)
        
        logger.info("Total rows extracted: %d", total_rows)

    except Exception as exc:
        logger.exception("extract_csv failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)
    return total_rows


if __name__ == "__main__":
    run()
