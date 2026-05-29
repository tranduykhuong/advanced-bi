---
name: etl-stage-to-ods
description: "ETL skill for transforming and loading data from PostgreSQL staging tables into the ODS layer. Use when implementing the stage → ODS pipeline: extracting from stage.* tables, applying business rules, enriching country data, and bulk UPSERT into ods.* tables."
---

# ETL: Stage → ODS

Generate extract, transform, and load scripts for the Stage → ODS pipeline.

## When to Use

Use when asked to write an ETL pipeline from `stage.*` tables into `ods.*` tables.

**Trigger phrases:** "stage to ODS", "ETL stage to ODS", "apply business rules", "country enrichment", "UPSERT into ODS"

## Two Pipelines in This Project

### Pipeline 1: Trade Transactions (3 sources → 1 ODS table)
```
stage.stage_csv + stage.stage_text + stage.stage_db
  → extract_stage.py       (UNION ALL, Vietnam filter)
  → stage_to_ods.py        (country enrichment, HS code parse, quality flags)
  → stage_to_ods.py (load) (aggregate by business key, UPSERT ods.trade_transaction)
```

### Pipeline 2: FTA
```
stage.stage_aptiad
  → extract_stage_aptiad.py
  → fta_stage_to_ods.py    (Yes/No→bool, year cast, status/scope normalize)
  → load_fta_to_ods.py     (UPSERT ods.fta on aptiad_no)
```

## Workflow

1. **Write extract script** — see [EXTRACT-STAGE.md](references/EXTRACT-STAGE.md)
2. **Write transform script with business rules** — see [BUSINESS-RULES.md](references/BUSINESS-RULES.md)
3. **Add country enrichment if needed** — see [COUNTRY-ENRICHMENT.md](references/COUNTRY-ENRICHMENT.md)
4. **Write load script with UPSERT** — see [UPSERT-ODS.md](references/UPSERT-ODS.md)
5. **Register in `run_pipeline.py`** under `stage-ods` phase group

## Key Rules

- Use `psycopg2.extras.execute_values` for UPSERT — `df.to_sql()` has no `ON CONFLICT` support
- Use chunked reading (`DEFAULT_CHUNK_SIZE`) for large extracted files
- Aggregate by business key before UPSERT to avoid conflict on duplicate rows
- All steps must run in the **same Docker container** (chain with `&&`)
- `updated_at = NOW()` must be in every `DO UPDATE SET` clause
