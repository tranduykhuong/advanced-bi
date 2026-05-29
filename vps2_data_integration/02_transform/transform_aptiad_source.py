"""Transform extracted APTIAD CSV: rename columns, trim values, add lineage."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.aptiad_columns import (
    STAGE_DATA_COLUMNS,
    build_rename_map,
    parse_snapshot_date,
)
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


def _strip_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if col in ("aptiad_no", "snapshot_date", "__source_file__"):
            continue
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": None, "None": None, "": None})
    return df


def run(batch_id: uuid.UUID | None = None) -> pd.DataFrame:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "transform_aptiad_source")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "aptiad_extracted.csv"
        output_file = tmp_dir / "aptiad_transformed.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Extracted artifact not found: {input_file}")

        df = pd.read_csv(input_file, dtype=str, encoding="utf-8-sig")

        source_files = df.pop("__source_file__") if "__source_file__" in df.columns else None
        rename_map = build_rename_map(list(df.columns))
        df = df.rename(columns=rename_map)

        df = _strip_text_columns(df)

        if source_files is not None:
            df["source_file"] = source_files
            df["snapshot_date"] = source_files.apply(
                lambda name: parse_snapshot_date(str(name))
            )
        else:
            df["source_file"] = None
            df["snapshot_date"] = None

        df["aptiad_no"] = pd.to_numeric(df["aptiad_no"], errors="coerce").astype("Int64")

        for col in STAGE_DATA_COLUMNS:
            if col not in df.columns:
                df[col] = None

        output_cols = [*STAGE_DATA_COLUMNS, "source_file", "snapshot_date"]
        df = df[output_cols]
        df.to_csv(output_file, index=False)

        rows_processed = len(df)
        logger.info("Transformed %s rows → %s", rows_processed, output_file)

    except Exception as exc:
        logger.exception("transform_aptiad_source failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_processed)

    return df


if __name__ == "__main__":
    result = run()
    print(f"Transformed {len(result)} rows → tmp/aptiad_transformed.csv")
