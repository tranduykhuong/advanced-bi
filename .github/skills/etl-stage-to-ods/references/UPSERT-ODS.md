# Load ODS Script Template

File: `03_load/load_{entity}_to_ods.py` or `03_load/stage_to_ods.py`

## Full Script Pattern

```python
"""Load transformed {entity} records into ods.{entity} (SCD Type 1 UPSERT)."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

TABLE_DDL = """..."""  # see ods-database-design skill

BUSINESS_KEY_COLS = ["year", "month", "hs_code", "partner_code", "flow_type", "source_system"]
INSERT_COLS = ["year", "quarter", "month", "hs_code", "partner_code", "partner_name",
               "flow_type", "value", "quantity", "source_system", "batch_id", ...]
UPDATE_COLS = [c for c in INSERT_COLS if c not in ("source_system",)]


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "load_{entity}_to_ods")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "{entity}_to_ods_transformed.csv"
        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        df = pd.read_csv(input_file, low_memory=False, keep_default_na=False)

        # Aggregate by business key (sums value/quantity, deduplicates)
        df = df.groupby(BUSINESS_KEY_COLS, as_index=False).agg({
            "value": "sum",
            "quantity": "sum",
            "partner_name": "first",
            "batch_id": "first",
            # ... other columns: "first"
        })

        # Create table
        with engine.begin() as conn:
            conn.execute(text(TABLE_DDL))

        # Build records
        records = [
            tuple(row[c] for c in INSERT_COLS)
            for _, row in df.iterrows()
        ]

        upsert_query = f"""
            INSERT INTO ods.{entity} ({", ".join(INSERT_COLS)})
            VALUES %s
            ON CONFLICT ({", ".join(BUSINESS_KEY_COLS)}) DO UPDATE SET
                {", ".join(f"{col} = EXCLUDED.{col}" for col in UPDATE_COLS)},
                updated_at = NOW()
        """

        with engine.begin() as conn:
            raw_conn = conn.connection
            cursor = raw_conn.cursor()
            execute_values(cursor, upsert_query, records, page_size=500)
            raw_conn.commit()

        logger.info("Upserted %d rows into ods.{entity}", len(df))

    except Exception as exc:
        logger.exception("load_{entity}_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))
    return len(df)


if __name__ == "__main__":
    run()
```

## Data Preparation Before UPSERT

```python
def _prepare_for_db(df: pd.DataFrame, batch_id: uuid.UUID) -> pd.DataFrame:
    df = df.copy()

    # Boolean columns
    for col in ["flow_type", "is_late_arriving", "has_trade_goods"]:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)

    # Array columns — must be actual Python lists, not strings
    for col in ["quality_flags", "fta_keys", "member_countries"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

    # Numeric columns
    for col in ["year", "quarter", "month"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    for col in ["value", "quantity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # batch_id normalization
    if "batch_id" in df.columns:
        df["batch_id"] = df["batch_id"].apply(
            lambda x: batch_id if pd.isna(x) or str(x).strip() == "" else uuid.UUID(str(x))
        )

    return df
```
