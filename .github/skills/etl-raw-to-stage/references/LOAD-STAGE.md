# Load Stage Script Template

File: `03_load/load_stage_{source}.py`

```python
"""Load transformed {source} data into stage.stage_{source}."""
from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

# Use importlib for modules in numerically-prefixed directories (e.g. "02_transform")
_transform = importlib.import_module("02_transform.transform_{source}_source")

logger = get_logger(__name__)

TABLE_DDL = """
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_{source} (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    column_a TEXT,
    column_b TEXT,
    value_col NUMERIC,
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
        batch_id = register_batch(engine, "load_stage_{source}")

    rows_loaded = 0
    try:
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))

        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE stage.stage_{source}"))

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        if not (tmp_dir / "{source}_extracted.csv").exists():
            logger.warning("Extracted file not found — skipping.")
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        df = _transform.run(batch_id=batch_id)
        df["batch_id"] = str(batch_id)

        df.to_sql("stage_{source}", engine, schema="stage", if_exists="append", index=False)
        rows_loaded = len(df)
        logger.info("Loaded %d rows into stage.stage_{source}", rows_loaded)

    except Exception as exc:
        logger.exception("load_stage_{source} failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_loaded)
    return rows_loaded


if __name__ == "__main__":
    run()
```
