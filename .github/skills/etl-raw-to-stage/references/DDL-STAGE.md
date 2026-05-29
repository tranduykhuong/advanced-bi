# Staging Table DDL Rules

## Column Type Rules

| Type | Use | Reason |
|------|-----|--------|
| `TEXT` | All string columns from source | Avoids `StringDataRightTruncation` — source lengths are unpredictable |
| `NUMERIC` | Monetary values, quantities | Exact precision; avoid `FLOAT` |
| `DATE` | Calendar dates | Snapshot date from filename |
| `UUID` | Surrogate key, batch reference | Use `gen_random_uuid()` not `SERIAL` |
| `TIMESTAMP` | Ingestion time | `DEFAULT NOW()` |

## Required Metadata Columns

Every staging table must include:

```sql
source_file   TEXT,               -- source filename (for lineage)
snapshot_date DATE,               -- date parsed from filename
batch_id      UUID,               -- links to public.etl_batch_log
extracted_at  TIMESTAMP DEFAULT NOW()
```

## DDL Template

```sql
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_{source} (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source columns (all TEXT in staging)
    col_a         TEXT,
    col_b         TEXT,
    amount        NUMERIC,

    -- Metadata
    source_file   TEXT,
    snapshot_date DATE,
    batch_id      UUID,
    extracted_at  TIMESTAMP DEFAULT NOW()
);
```

## Load Strategy

- Always `TRUNCATE` before load → fresh load, no duplicates
- Use `CREATE TABLE IF NOT EXISTS` → idempotent, safe to re-run
- No UNIQUE constraints in staging — deduplication happens in ODS
