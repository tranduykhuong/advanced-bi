---
name: etl-raw-to-stage
description: "ETL skill for loading raw data files from raw_data/ into PostgreSQL staging tables. Use when implementing extract → transform → load pipelines for CSV, text, database, or any file-based source."
---

# ETL: raw_data → Stage

Generate extract, transform, and load scripts to ingest raw data files into PostgreSQL staging tables.

## When to Use

Use when asked to write an ETL pipeline for a new data source into `stage.*` tables.

**Trigger phrases:** "ETL from raw_data", "load into stage", "staging table", "extract CSV", "new data source"

## Workflow

1. **Understand the source** — file type (CSV/text/DB), location, column names, encoding
2. **Design the staging table** — see [DDL-STAGE.md](references/DDL-STAGE.md)
3. **Write the extract script** — see [EXTRACT.md](references/EXTRACT.md)
4. **Write the transform script** — see [TRANSFORM.md](references/TRANSFORM.md)
5. **Write the load script** — see [LOAD-STAGE.md](references/LOAD-STAGE.md)
6. **Register in `run_pipeline.py`** under the appropriate PHASES list

## Key Rules

- Every script has a `run(batch_id)` function and uses `register_batch` / `complete_batch`
- Extract saves to `tmp/{source}_extracted.csv`; transform reads from it
- All steps must run in the **same Docker container** (chain with `&&` in one `bash -c`)
- Staging tables use `TEXT` for all string columns and `TRUNCATE` before each load
- Import numerically-prefixed modules with `importlib.import_module("02_transform.transform_{source}_source")`

## Source-Specific Notes

| Source | Encoding | Key Flag | Notes |
|--------|----------|----------|-------|
| UN Comtrade CSV | `latin-1` | `index_col=False` | Trailing comma causes column shift without this flag |
| NSO Text | `utf-8` | — | Extract to JSONL; transform parses month rows |
| Trade Map DB | — | `get_vps1_engine(cfg)` | Read from VPS1 PostgreSQL, no transform step |
| APTIAD CSV | `utf-8-sig` | — | Parse snapshot date from filename |
