# Transform Script Template

File: `02_transform/transform_{source}_source.py`

```python
"""Transform extracted {source} data: rename columns, cast types, clean text."""
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

# Map source column names → staging snake_case names
COLUMN_RENAME_MAP = {
    "SourceColumnA": "stage_column_a",
    "SourceColumnB": "stage_column_b",
}

NUMERIC_COLUMNS = ("value_col", "quantity_col")


def run(batch_id: uuid.UUID | None = None) -> pd.DataFrame:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "transform_{source}_source")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "{source}_extracted.csv"
        output_file = tmp_dir / "{source}_transformed.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Extracted artifact not found: {input_file}")

        # Always read as str — prevents pandas from auto-detecting "True"/"False" as bool
        df = pd.read_csv(input_file, dtype=str)
        df = df.rename(columns=COLUMN_RENAME_MAP)

        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Trim all text columns
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].str.strip().replace({"nan": None, "None": None, "": None})

        df.to_csv(output_file, index=False)
        logger.info("Transformed %d rows → %s", len(df), output_file)

    except Exception as exc:
        logger.exception("transform_{source}_source failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))
    return df


if __name__ == "__main__":
    df = run()
    print(f"Transformed {len(df)} rows")
```
