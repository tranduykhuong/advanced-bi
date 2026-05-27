---
description: CSV extraction from UN Comtrade sources and load into staging database layer
applyTo: "**/vps2_data_integration/**/*.py"
---

# CSV Extraction & Staging Skill

## Overview

This skill covers the complete ETL process for UN Comtrade CSV data into the staging layer (`stage.stage_csv`), following an Extract → Transform → Load pattern.

**Scope:**
- Extract CSV files from `raw_data/csv_source/` directory
- Select required columns (16 columns from UN Comtrade format)
- Transform: rename camelCase columns to snake_case + cast numeric types
- Load into PostgreSQL staging table with batch tracking

---

## Architecture

### Data Flow

```
raw_data/csv_source/*.csv
         ↓
    [extract_csv.py]
    - Read CSV files (encoding="latin-1", index_col=False)
    - Select required columns (usecols=REQUIRED_COLUMNS)
    - Concatenate DataFrames
    - Save to tmp/trade_extracted.csv
         ↓
    [transform_csv_source.py]
    - Read tmp/trade_extracted.csv (dtype=str)
    - Rename columns: camelCase → snake_case
    - Cast numeric columns via pd.to_numeric(errors="coerce")
    - Save to tmp/trade_transformed.csv
    - Return DataFrame
         ↓
   [load_stage_csv.py]
    - Create schema + table (CREATE TABLE IF NOT EXISTS)
    - TRUNCATE for fresh load
    - Call transform_csv_source.run() → DataFrame
    - Insert via pandas.to_sql()
    - Register batch completion
         ↓
  stage.stage_csv (17 columns + metadata)
```

### Components

| Component | Path | Purpose |
|-----------|------|---------|
| **Extract** | `01_extract/extract_csv.py` | CSV file reader & aggregator |
| **Transform** | `02_transform/transform_csv_source.py` | Column rename + numeric type casting |
| **Load** | `03_load/load_stage_csv.py` | Database loader & DDL handler |
| **Pipeline** | `run_pipeline.py` | Orchestrator (Phase 01 → Phase 03) |

---

## Key Implementation Details

### 1. CSV Extraction (`extract_csv.py`)

**Required Columns** (16 total):
```
period, cmdCode, cmdDesc, reporterISO, partnerISO, partnerDesc,
flowCode, flowDesc, primaryValue, cifvalue, fobvalue, netWgt,
qty, qtyUnitAbbr, motCode, motDesc
```

**Critical read_csv flags:**
```python
df = pd.read_csv(
    csv_file,
    usecols=REQUIRED_COLUMNS,
    low_memory=False,
    encoding="latin-1",   # UN Comtrade files use latin-1, not UTF-8
    index_col=False,       # Trailing comma in rows causes pandas to treat col 0 as index; this prevents column shift
)
```

**Why `index_col=False` is critical:**
UN Comtrade CSV files have a trailing comma on every data row (47 header columns, 48 data values per row). Without `index_col=False`, pandas treats the first column as a row index — shifting all data right by one position. This causes `period` to contain `36` instead of `202601`, `reporter_iso` to contain wrong values, etc.

**Why `encoding="latin-1"`:**
UN Comtrade CSV files contain special characters (e.g., accented letters in country/product names) encoded in latin-1. Reading with the default UTF-8 raises `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb2`.

**Process:**
```python
1. Load config & setup logging
2. Register batch (ETL batch tracking)
3. Create tmp/ directory if not exists
4. Iterate through raw_data/csv_source/*.csv
5. For each CSV:
   - Read with pandas.read_csv(usecols, encoding="latin-1", index_col=False)
   - Append to list
   - Log row counts
6. Concatenate all DataFrames
7. Save combined output to tmp/trade_extracted.csv
8. Complete batch with rows_loaded count
```

**Error Handling:**
- Missing CSV directory → Warning + skip (0 rows)
- Column mismatch → Exception + batch FAILED
- File I/O errors → Exception + batch FAILED

---

### 2. CSV Transformation (`transform_csv_source.py`)

**Responsibility:** BI-layer transformations — column rename (camelCase → snake_case) and numeric type casting.

**Column Rename Map:**
```python
COLUMN_RENAME_MAP = {
    "cmdCode":      "cmd_code",
    "cmdDesc":      "cmd_desc",
    "reporterISO":  "reporter_iso",
    "partnerISO":   "partner_iso",
    "partnerDesc":  "partner_desc",
    "flowCode":     "flow_code",
    "flowDesc":     "flow_desc",
    "primaryValue": "primary_value",
    "cifvalue":     "cif_value",
    "fobvalue":     "fob_value",
    "netWgt":       "net_wgt",
    "qtyUnitAbbr":  "qty_unit",
    "motCode":      "mot_code",
    "motDesc":      "mot_desc",
}

NUMERIC_COLUMNS = ("primary_value", "cif_value", "fob_value", "net_wgt", "qty")
```

**Why `dtype=str` on read:**
UN Comtrade numeric columns may contain `"True"/"False"` or other non-numeric strings. Pandas auto-detection converts these to Python booleans, which causes `DatatypeMismatch: column "qty" is of type numeric but expression is of type boolean` on insert. Reading all columns as `str` first, then explicitly casting with `pd.to_numeric(errors="coerce")`, prevents this.

```python
def run() -> pd.DataFrame:
    df = pd.read_csv(input_file, dtype=str)       # prevent bool auto-detection
    df = df.rename(columns=COLUMN_RENAME_MAP)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.to_csv(output_file, index=False)
    return df
```

---

### 3. CSV Loading (`load_stage_csv.py`)

**Import pattern** (module in numerically-prefixed directory):
```python
import importlib
_transform = importlib.import_module("02_transform.transform_csv_source")
# Called as: df = _transform.run()
```

**Table Schema:**
```sql
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_csv (
    id BIGSERIAL PRIMARY KEY,
    period TEXT,
    cmd_code TEXT,
    cmd_desc TEXT,
    reporter_iso TEXT,
    partner_iso TEXT,
    partner_desc TEXT,
    flow_code TEXT,
    flow_desc TEXT,
    primary_value NUMERIC,
    cif_value NUMERIC,
    fob_value NUMERIC,
    net_wgt NUMERIC,
    qty NUMERIC,
    qty_unit TEXT,
    mot_code TEXT,
    mot_desc TEXT,
    batch_id TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);
```

**Why TEXT instead of VARCHAR(n):**
UN Comtrade `reporter_iso` values include full country names (e.g., `"Australia"`) not just ISO-3 codes. Using `VARCHAR(3)` causes `StringDataRightTruncation`. TEXT avoids all truncation issues in the staging layer.

**Process:**
```python
1. Load config & setup logging
2. Register batch
3. Execute TABLE_DDL (CREATE SCHEMA + CREATE TABLE IF NOT EXISTS)
4. TRUNCATE stage.stage_csv (fresh load)
5. Check tmp/trade_extracted.csv exists
6. Call _transform.run() → returns renamed + cast DataFrame
7. Add batch_id column
8. Insert via df.to_sql(..., dtype={col: Float()})
9. Complete batch with rows_loaded count
```

**to_sql dtype override** (prevents bool → numeric mismatch):
```python
df.to_sql(
    "stage_csv", engine, schema="stage", if_exists="append", index=False,
    dtype={
        "primary_value": Float(),
        "cif_value":     Float(),
        "fob_value":     Float(),
        "net_wgt":       Float(),
        "qty":           Float(),
    },
)
```

---

### 4. Pipeline Integration

**run_pipeline.py phases (relevant):**
```
Phase 01: Extract CSV Files     ← 01_extract/extract_csv.py
Phase 02: Transform TXT → Stage ← 02_transform/transform_text_source.py
Phase 03: Load stage_csv        ← 03_load/load_stage_csv.py
                                   (internally calls transform_csv_source.run())
```

**Running in same container (required for tmp/ file sharing):**
```bash
docker compose run --rm etl_engine sh -c \
  "python 01_extract/extract_csv.py && python 03_load/load_stage_csv.py"
```

Each `docker compose run` creates a new container — `tmp/trade_extracted.csv` from the extract step disappears if load runs in a separate container.

---

## Column Mapping

| CSV Column | Destination Column | Type | Notes |
|------------|-------------------|------|-------|
| period | period | TEXT | Format: YYYYMM (e.g. 202601) |
| cmdCode | cmd_code | TEXT | HS product code |
| cmdDesc | cmd_desc | TEXT | Product description |
| reporterISO | reporter_iso | TEXT | May contain full names, not just ISO-3 |
| partnerISO | partner_iso | TEXT | May contain full names |
| partnerDesc | partner_desc | TEXT | Country/region name |
| flowCode | flow_code | TEXT | Export/Import code |
| flowDesc | flow_desc | TEXT | Flow type description |
| primaryValue | primary_value | NUMERIC | Trade value in USD |
| cifvalue | cif_value | NUMERIC | CIF value |
| fobvalue | fob_value | NUMERIC | FOB value |
| netWgt | net_wgt | NUMERIC | Net weight |
| qty | qty | NUMERIC | Quantity |
| qtyUnitAbbr | qty_unit | TEXT | Unit abbreviation |
| motCode | mot_code | TEXT | Mode of transport code |
| motDesc | mot_desc | TEXT | Mode description |

---

## Usage

### Run Full Pipeline
```bash
cd vps2_data_integration
python run_pipeline.py
```

### Run Extract + Load (in same container)
```bash
docker compose run --rm etl_engine sh -c \
  "python 01_extract/extract_csv.py && python 03_load/load_stage_csv.py"
```

### Run Extract Only (Debug)
```bash
python 01_extract/extract_csv.py
```

### Run Transform Only (Debug)
```bash
python 02_transform/transform_csv_source.py
# Prints: "Transformed N rows → tmp/trade_transformed.csv"
```

### Run Load Only (Debug)
```bash
python 03_load/load_stage_csv.py
```

---

## Monitoring & Troubleshooting

### Check Batch Status
```sql
SELECT * FROM public.etl_batch_log
WHERE batch_name LIKE '%extract_csv%' OR batch_name LIKE '%load_stage_csv%'
ORDER BY started_at DESC
LIMIT 10;
```

### Verify Staging Data
```sql
SELECT COUNT(*) FROM stage.stage_csv;
SELECT DISTINCT period FROM stage.stage_csv ORDER BY period DESC;
SELECT period, reporter_iso, partner_iso, cmd_code, primary_value
FROM stage.stage_csv LIMIT 10;
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb2` | CSV is latin-1 encoded | Add `encoding="latin-1"` to `pd.read_csv()` |
| `column "reporterISO" does not exist` | camelCase column not renamed before insert | Ensure transform step runs before load |
| `StringDataRightTruncation` | VARCHAR(n) too small for actual data | Use TEXT for all string columns in DDL |
| `DatatypeMismatch: expression is of type boolean` | pandas auto-detects "True"/"False" as bool | Read CSV with `dtype=str`; rebuild Docker with `--no-cache` |
| All data shifted by 1 column (period=36 instead of 202601) | Trailing comma in CSV rows causes pandas index shift | Add `index_col=False` to `pd.read_csv()` |
| 0 rows loaded | `tmp/trade_extracted.csv` missing (different containers) | Run extract + load in same container via `sh -c "..."` |
| 0 rows loaded | CSV source dir not found | Check `RAW_DATA_PATH` env var |

---

## Dependencies

**Python Packages:**
- pandas (CSV reading/writing, type casting)
- sqlalchemy (database connection, to_sql)
- psycopg2-binary (PostgreSQL adapter)

**Environment Variables:**
- `RAW_DATA_PATH` → Path to `vps1_data_sources/raw_data/`
- `DB_PASSWORD` / `POSTGRES_PASSWORD` → Database credential
- Other config from `config.py`

---

## Design Principles

### Idempotent Design
- `CREATE TABLE IF NOT EXISTS` → Safe to re-run
- `TRUNCATE` before load → No duplicate rows
- Batch tracking → Full audit trail in `public.etl_batch_log`

### ETL Separation of Concerns
- **Extract**: only reads raw files, saves raw CSV to `tmp/`
- **Transform**: only renames/casts, no DB interaction, returns DataFrame
- **Load**: only handles DB (DDL, truncate, insert), delegates transform to transform module

### Defensive Type Handling
- Always read source CSV with `dtype=str` in transform step
- Always specify `dtype={col: Float()}` in `to_sql` for numeric columns
- Numeric cast uses `errors="coerce"` — invalid values become NaN, not errors

---

## Version History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-27 | ETL Team | Add transform_csv_source.py; separate transform from load; fix latin-1, index_col, dtype bool bugs |
| 2026-05-27 | ETL Team | Initial: CSV extract + load implementation |
