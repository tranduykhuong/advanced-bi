"""Extract APTIAD rows from stage.stage_aptiad into tmp/fta_stage_extracted.csv."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_stage_aptiad")

    try:
        query = "SELECT * FROM stage.stage_aptiad"

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "fta_stage_extracted.csv"

        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), conn)

        logger.info("Extracted %s rows from stage.stage_aptiad", len(df))
        df.to_csv(output_file, index=False)

    except Exception as exc:
        logger.exception("extract_stage_aptiad failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))

    return len(df)


if __name__ == "__main__":
    run()
