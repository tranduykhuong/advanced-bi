---
description: Extract ITC Trade Map relational data from VPS1 source DB and load into staging database layer
applyTo: "**/vps2_data_integration/**/*.py"
---

# Trade Map Extraction & Staging Skill

## Overview

This skill covers the complete ETL process for ITC Trade Map data from the VPS1 source database (`trademap_db`) into the staging layer (`stage.stage_db`), following an Extract → Transform → Load pattern.

**Scope:**
- Extract denormalized trade rows from VPS1 PostgreSQL (`country`, `product`, `trade_record`)
- Select and flatten joined columns (exporter/importer names, product label)
- Transform: derive `period` (YYYYMM), cast numeric types, normalize text
- Load into PostgreSQL staging table on VPS3 with batch tracking

**Prerequisite:** Trade Map CSV files must already be ingested into VPS1 via `vps1_data_sources/trademap_ingest/ingest_trademap.py` (manual step, not CI/CD).

---

## Architecture

### Data Flow

```
VPS1: trademap_db
  country ──┐
  product ──┼── trade_record (FK: exporter_id, importer_id, product_code)
            ↓
    [extract_trademap.py]
    - Connect to VPS1 PostgreSQL (VPS1_DB_* env vars)
    - Run JOIN query (trade_record + country + product)
    - Save to tmp/trademap_extracted.csv
            ↓
    [transform_trademap_source.py]
    - Read tmp/trademap_extracted.csv (dtype=str)
    - Normalize country/product text (mojibake fix)
    - Derive period = YYYYMM from year + month
    - Cast value_usd_k via pd.to_numeric(errors="coerce")
    - Save to tmp/trademap_transformed.csv
    - Return DataFrame
            ↓
   [load_stage_db.py]
    - Create schema + table (CREATE TABLE IF NOT EXISTS)
    - TRUNCATE for fresh load
    - Call transform_trademap_source.run() → DataFrame
    - Insert via pandas.to_sql()
    - Register batch completion
            ↓
  VPS3: stage.stage_db (denormalized + metadata)
```

### Components

| Component | Path | Purpose |
|-----------|------|---------|
| **Extract** | `01_extract/extract_trademap.py` | VPS1 DB reader & CSV snapshot |
| **Transform** | `02_transform/transform_trademap_source.py` | Text normalize + period derive + numeric cast |
| **Load** | `03_load/load_stage_db.py` | Database loader & DDL handler |
| **Pipeline** | `run_pipeline.py` | Orchestrator (add Phase 01c after extract_csv) |

---

## Source Schema (VPS1)

Reference: `vps1_data_sources/trademap_ingest/schema.sql`

```sql
-- country: master list of countries/territories
CREATE TABLE country (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

-- product: HS codes + TOTAL
CREATE TABLE product (
    code VARCHAR(50) PRIMARY KEY,
    label TEXT NOT NULL
);

-- trade_record: bilateral monthly values (USD thousands)
CREATE TABLE trade_record (
    id SERIAL PRIMARY KEY,
    exporter_id INT NOT NULL REFERENCES country(id),
    importer_id INT NOT NULL REFERENCES country(id),
    product_code VARCHAR(50) NOT NULL REFERENCES product(code),
    year INT NOT NULL,
    month INT NOT NULL,
    value_usd_k NUMERIC,
    UNIQUE (exporter_id, importer_id, product_code, year, month)
);
```

**Domain notes:**
- Bilateral ingest focus: **exporter** = source country (Zambia, Türkiye, …), **importer** = `Viet Nam` (fixed)
- `product_code` includes `TOTAL` (aggregate) and individual HS codes
- `value_usd_k` = trade value in **USD thousands** (not full USD like UN Comtrade `primaryValue`)
- `year` + `month` are separate integers (month 1–12), not a single `period` column

---

## Key Implementation Details

### 1. Trade Map Extraction (`extract_trademap.py`)

**Extract Query** (denormalize IDs → names):

```sql
SELECT
    c_exp.name   AS exporter_name,
    c_imp.name   AS importer_name,
    tr.product_code,
    p.label      AS product_label,
    tr.year,
    tr.month,
    tr.value_usd_k
FROM trade_record tr
JOIN country c_exp ON c_exp.id = tr.exporter_id
JOIN country c_imp ON c_imp.id = tr.importer_id
LEFT JOIN product p ON p.code = tr.product_code
ORDER BY tr.year DESC, tr.month DESC, c_exp.name, tr.product_code;
```

**Dual-database connection pattern:**

```python
from sqlalchemy import create_engine, text
import pandas as pd

def get_vps1_engine() -> Engine:
    """Separate engine for VPS1 source DB — NOT the warehouse engine."""
    url = (
        f"postgresql+psycopg2://{vps1_user}:{vps1_password}"
        f"@{vps1_host}:{vps1_port}/{vps1_dbname}"
    )
    return create_engine(url, pool_pre_ping=True)

def run() -> int:
    engine = get_vps1_engine()
    df = pd.read_sql(EXTRACT_SQL, engine)
    df.to_csv(tmp_dir / "trademap_extracted.csv", index=False)
    return len(df)
```

**Optional filters** (add to WHERE clause when needed):

```sql
-- Only bilateral exports to Viet Nam
AND c_imp.name = 'Viet Nam'

-- Date range
AND tr.year >= 2020

-- Exclude TOTAL aggregate (product-level only)
AND tr.product_code <> 'TOTAL'
```

**Process:**
```python
1. Load config & setup logging
2. Register batch (ETL batch tracking on VPS3 warehouse)
3. Create tmp/ directory if not exists
4. Connect to VPS1 trademap_db
5. Execute EXTRACT_SQL → pandas DataFrame
6. Log row counts + distinct exporters/importers
7. Save to tmp/trademap_extracted.csv
8. Complete batch with rows_extracted count
```

**Error Handling:**
- VPS1 connection refused → Exception + batch FAILED (check VPS1_DB_HOST / firewall)
- Empty trade_record → Warning + 0 rows (ingest not run yet on VPS1)
- Missing FK joins → Log warning; rows with NULL names should be filtered in transform

---

### 2. Trade Map Transformation (`transform_trademap_source.py`)

**Responsibility:** BI-layer transformations — text normalization, period derivation, numeric casting.

**Column definitions after transform:**

```python
OUTPUT_COLUMNS = (
    "exporter_name",
    "importer_name",
    "product_code",
    "product_label",
    "year",
    "month",
    "period",        # derived: f"{year:04d}{month:02d}"
    "value_usd_k",
)

NUMERIC_COLUMNS = ("year", "month", "value_usd_k")
TEXT_COLUMNS = ("exporter_name", "importer_name", "product_code", "product_label", "period")
```

**Text normalization** (reuse logic from `ingest_trademap.py`):

```python
def _normalize_trademap_text(value: object) -> str:
    """Fix common mojibake in Trade Map Latin-1 / Windows exports."""
    text = str(value).strip()
    return text.replace("\x99", "ô").replace("™", "ô")
```

**Why `dtype=str` on read:**
Source extract may contain mixed encodings from VPS1 ingest. Reading all columns as `str` first prevents pandas bool auto-detection on edge values.

```python
def run() -> pd.DataFrame:
    df = pd.read_csv(input_file, dtype=str)
    for col in ("exporter_name", "importer_name", "product_label"):
        if col in df.columns:
            df[col] = df[col].map(_normalize_trademap_text)
    df["product_code"] = df["product_code"].str.strip().str.lstrip("'")
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["year", "month", "exporter_name", "importer_name"])
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["period"] = df["year"].astype(str).str.zfill(4) + df["month"].astype(str).str.zfill(2)
    df.to_csv(output_file, index=False)
    return df
```

---

### 3. Trade Map Loading (`load_stage_db.py`)

**Import pattern** (module in numerically-prefixed directory):

```python
import importlib
_transform = importlib.import_module("02_transform.transform_trademap_source")
# Called as: df = _transform.run()
```

**Table Schema:**

```sql
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE IF NOT EXISTS stage.stage_db (
    id BIGSERIAL PRIMARY KEY,
    exporter_name TEXT NOT NULL,
    importer_name TEXT NOT NULL,
    product_code TEXT NOT NULL,
    product_label TEXT,
    year INT NOT NULL,
    month INT NOT NULL,
    period TEXT NOT NULL,
    value_usd_k NUMERIC,
    batch_id TEXT,
    extracted_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stage_db_period
    ON stage.stage_db (period);
CREATE INDEX IF NOT EXISTS idx_stage_db_exporter
    ON stage.stage_db (exporter_name);
```

**Why TEXT instead of VARCHAR(n):**
Country names from Trade Map include full names with accents and special characters (e.g., `Türkiye`, `Côte d'Ivoire`). TEXT avoids truncation in the staging layer.

**Process:**
```python
1. Load config & setup logging
2. Register batch (on VPS3 warehouse engine)
3. Execute TABLE_DDL (CREATE SCHEMA + CREATE TABLE IF NOT EXISTS)
4. TRUNCATE stage.stage_db (fresh load)
5. Check tmp/trademap_extracted.csv exists
6. Call _transform.run() → returns normalized + cast DataFrame
7. Add batch_id column
8. Insert via df.to_sql(..., dtype={col: Float()})
9. Complete batch with rows_loaded count
```

**to_sql dtype override:**

```python
df.to_sql(
    "stage_db", engine, schema="stage", if_exists="append", index=False,
    dtype={
        "year":          Float(),
        "month":         Float(),
        "value_usd_k":   Float(),
    },
)
```

---

### 4. Pipeline Integration

**run_pipeline.py phases (add after extract_csv):**

```
Phase 01a: Extract API              ← 01_extract/extract_api.py
Phase 01b: Extract TXT Files        ← 01_extract/extract_txt_files.py
Phase 01c: Extract Trade Map (VPS1) ← 01_extract/extract_trademap.py   [NEW]
Phase 02:  Transform TXT → Stage    ← 02_transform/transform_text_source.py
Phase 03:  Load stage_csv           ← 03_load/load_stage_csv.py
Phase 03b: Load stage_db            ← 03_load/load_stage_db.py   [NEW]
                                           (internally calls transform_trademap_source.run())
```

**Running in same container (required for tmp/ file sharing):**

```bash
docker compose run --rm etl_engine sh -c \
  "python 01_extract/extract_trademap.py && python 03_load/load_stage_db.py"
```

Each `docker compose run` creates a new container — `tmp/trademap_extracted.csv` from the extract step disappears if load runs in a separate container.

**Production (VPS2 → VPS1 over network):**

```bash
# .env on VPS2 must set VPS1_DB_HOST to VPS1 public IP
VPS1_DB_HOST=134.209.99.243
VPS1_DB_PORT=5433
VPS1_POSTGRES_DB=trademap_db
VPS1_POSTGRES_USER=trademap_admin
VPS1_POSTGRES_PASSWORD=<secret>
```

---

## Column Mapping

| VPS1 Source | Staging Column | Type | Notes |
|-------------|---------------|------|-------|
| `country.name` (exporter) | exporter_name | TEXT | Via JOIN on exporter_id |
| `country.name` (importer) | importer_name | TEXT | Usually `Viet Nam` for bilateral files |
| `trade_record.product_code` | product_code | TEXT | HS code or `TOTAL` |
| `product.label` | product_label | TEXT | Via LEFT JOIN on product_code |
| `trade_record.year` | year | INT | e.g. 2024 |
| `trade_record.month` | month | INT | 1–12 |
| *(derived)* | period | TEXT | Format: YYYYMM (e.g. 202401) |
| `trade_record.value_usd_k` | value_usd_k | NUMERIC | USD **thousands** — multiply ×1000 for full USD |
| — | batch_id | TEXT | ETL batch UUID |
| — | extracted_at | TIMESTAMP | Load timestamp |

### Comparison with UN Comtrade staging (`stage.stage_csv`)

| Aspect | UN Comtrade (`stage_csv`) | Trade Map (`stage_db`) |
|--------|---------------------------|----------------------------|
| Source | CSV files in `raw_data/csv_source/` | VPS1 PostgreSQL `trademap_db` |
| Period | `period` column (YYYYMM text) | Derived from `year` + `month` |
| Value unit | Full USD (`primary_value`) | USD thousands (`value_usd_k`) |
| Geography | reporter_iso + partner_iso | exporter_name + importer_name (full names) |
| Product | cmd_code + cmd_desc | product_code + product_label |
| Flow | flow_code (Export/Import) | Implicit: bilateral export to importer |

---

## Usage

### Verify VPS1 source data first

```bash
docker exec postgres_vps1 psql -U trademap_admin -d trademap_db -c \
  "SELECT COUNT(*) FROM trade_record;"

docker exec postgres_vps1 psql -U trademap_admin -d trademap_db -c \
  "SELECT c_exp.name, COUNT(*) FROM trade_record tr
   JOIN country c_exp ON c_exp.id = tr.exporter_id
   GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"
```

### Run Extract + Load (in same container)

```bash
docker compose run --rm etl_engine sh -c \
  "python 01_extract/extract_trademap.py && python 03_load/load_stage_db.py"
```

### Run Extract Only (Debug)

```bash
python 01_extract/extract_trademap.py
# Output: tmp/trademap_extracted.csv
```

### Run Transform Only (Debug)

```bash
python 02_transform/transform_trademap_source.py
# Prints: "Transformed N rows → tmp/trademap_transformed.csv"
```

### Run Load Only (Debug)

```bash
python 03_load/load_stage_db.py
```

---

## Monitoring & Troubleshooting

### Check Batch Status

```sql
SELECT * FROM public.etl_batch_log
WHERE batch_name LIKE '%extract_trademap%' OR batch_name LIKE '%load_stage_db%'
ORDER BY started_at DESC
LIMIT 10;
```

### Verify Staging Data

```sql
SELECT COUNT(*) FROM stage.stage_db;

SELECT DISTINCT period FROM stage.stage_db ORDER BY period DESC;

SELECT exporter_name, importer_name, product_code, period, value_usd_k
FROM stage.stage_db
ORDER BY period DESC, exporter_name
LIMIT 20;

-- Compare row counts VPS1 vs staging
-- VPS1: SELECT COUNT(*) FROM trade_record;
-- VPS3: SELECT COUNT(*) FROM stage.stage_db;
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `connection refused` to VPS1 | VPS1_DB_HOST wrong or firewall | Set VPS1 public IP on VPS2; open port 5433 |
| `VPS1_DB_PASSWORD ... is required` | Missing env var in ETL container | Add VPS1_POSTGRES_PASSWORD to `.env` and docker-compose |
| 0 rows extracted | `trade_record` empty on VPS1 | Run `ingest_trademap.py` on VPS1 first |
| Staging count < VPS1 count | Transform dropped rows with NULL year/month | Check source data quality; log dropped count |
| Garbled country names (`Türkiye` → mojibake) | Latin-1 encoding in source | Apply `_normalize_trademap_text()` in transform |
| `value_usd_k` seems too small | Values are in USD **thousands** | Multiply by 1000 when comparing to Comtrade USD |
| 0 rows loaded | `tmp/trademap_extracted.csv` missing (different containers) | Run extract + load in same container via `sh -c "..."` |
| Duplicate staging rows on re-run | Missing TRUNCATE | Ensure `TRUNCATE stage.stage_db` before insert |

---

## Dependencies

**Python Packages:**
- pandas (SQL read, CSV I/O, type casting)
- sqlalchemy (dual DB connections, to_sql)
- psycopg2-binary (PostgreSQL adapter for VPS1 + VPS3)

**Environment Variables:**

| Variable | Target | Purpose |
|----------|--------|---------|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | VPS3 warehouse | Staging load destination |
| `VPS1_DB_HOST` | VPS1 | Source DB host (`postgres_vps1` local, public IP prod) |
| `VPS1_DB_PORT` / `VPS1_POSTGRES_PORT` | VPS1 | Source DB port (5433 mapped locally) |
| `VPS1_POSTGRES_DB` | VPS1 | Database name (default: `trademap_db`) |
| `VPS1_POSTGRES_USER` | VPS1 | DB user (default: `trademap_admin`) |
| `VPS1_POSTGRES_PASSWORD` | VPS1 | DB password (required) |

---

## Design Principles

### Idempotent Design
- `CREATE TABLE IF NOT EXISTS` → Safe to re-run
- `TRUNCATE` before load → No duplicate rows
- Batch tracking → Full audit trail in `public.etl_batch_log`

### ETL Separation of Concerns
- **Extract**: only reads VPS1 source DB, saves flat CSV to `tmp/`
- **Transform**: only normalizes/casts/derives, no DB interaction, returns DataFrame
- **Load**: only handles VPS3 warehouse (DDL, truncate, insert), delegates transform

### Defensive Type Handling
- Always read extracted CSV with `dtype=str` in transform step
- Always specify `dtype={col: Float()}` in `to_sql` for numeric columns
- Numeric cast uses `errors="coerce"` — invalid values become NaN, not errors

### Source-of-Truth Chain

```
Trade Map CSV (ITC export)
    → VPS1 ingest (ingest_trademap.py) → trademap_db
    → VPS2 extract (extract_trademap.py) → tmp/trademap_extracted.csv
    → VPS2 transform → tmp/trademap_transformed.csv
    → VPS3 load → stage.stage_db
    → (downstream) stage_to_ods → ods_to_nds → nds_to_dds_scd
```

VPS1 ingest remains **manual** (not CI/CD). VPS2 extract-to-staging can run on schedule or as part of `run_pipeline.py`.

---

## Version History

| Date | Author | Changes |
|------|--------|---------|
| 2026-05-28 | ETL Team | Initial: Trade Map VPS1 → stage.stage_db skill (mirrors csv-extract-to-staging pattern) |
