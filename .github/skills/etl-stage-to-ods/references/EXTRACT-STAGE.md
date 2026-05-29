# Extract from Stage Template

File: `01_extract/extract_stage_{entity}.py`

## Single Table Extract

```python
"""Extract stage.stage_{entity} → tmp/{entity}_stage_extracted.csv."""
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
        batch_id = register_batch(engine, "extract_stage_{entity}")

    try:
        query = "SELECT * FROM stage.stage_{entity}"

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "{entity}_stage_extracted.csv"

        with engine.connect() as conn:
            df = pd.read_sql_query(text(query), conn)

        df.to_csv(output_file, index=False)
        logger.info("Extracted %d rows → %s", len(df), output_file)

    except Exception as exc:
        logger.exception("extract_stage_{entity} failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))
    return len(df)


if __name__ == "__main__":
    run()
```

## UNION ALL (Multi-Source Extract)

When consolidating multiple staging tables into one ODS table:

```python
query = """
SELECT
    CAST(SUBSTRING(period::text, 1, 4) AS INTEGER) as year,
    CAST(SUBSTRING(period::text, 5, 2) AS INTEGER) as month,
    cmd_code as hs_code,
    NULL as product_name,
    reporter_iso as partner_code,
    NULL as partner_name,
    CASE WHEN LOWER(flow_desc) LIKE '%import%' THEN FALSE ELSE TRUE END as flow_type,
    primary_value as value,
    qty as quantity,
    qty_unit as unit,
    'UN_COMTRADE' as record_source,
    'stage_csv' as source_system
FROM stage.stage_csv

UNION ALL

SELECT
    year, month,
    NULL as hs_code, goods as product_name,
    NULL as partner_code, country as partner_name,
    flow_type, value, COALESCE(quantity, 0), 'ton', 'NSO', 'stage_text'
FROM stage.stage_text

UNION ALL

SELECT
    year, month,
    product_code, product_label,
    NULL,
    CASE
        WHEN TRIM(importer_name) ILIKE 'Viet Nam' THEN exporter_name
        ELSE importer_name
    END,
    CASE
        WHEN TRIM(importer_name) ILIKE 'Viet Nam' THEN FALSE
        ELSE TRUE
    END,
    value_usd_k * 1000, 0, '', 'TRADE_MAP', 'stage_db'
FROM stage.stage_db
WHERE product_code IS NOT NULL
  AND UPPER(TRIM(product_code)) != 'TOTAL'
  AND (TRIM(importer_name) ILIKE 'Viet Nam' OR TRIM(exporter_name) ILIKE 'Viet Nam')
"""
```
