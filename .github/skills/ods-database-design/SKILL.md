---
name: ods-database-design
description: "ODS database design skill for a Hybrid Inmon-Kimball data warehouse. Use when designing ODS tables, defining business keys for UPSERT deduplication, choosing column types, or implementing SCD Type 1 patterns."
---

# ODS Database Design

Design PostgreSQL ODS tables that consolidate staging data into typed, deduplicated records for the NDS layer.

## When to Use

Use when asked to design a new ODS table or define a UNIQUE constraint for UPSERT.

**Trigger phrases:** "ODS table", "design ODS", "business key", "UPSERT", "SCD Type 1", "ods.trade_transaction", "ods.fta"

## ODS vs Stage

| | Stage | ODS |
|---|---|---|
| Column types | All TEXT | Typed (BOOLEAN, INTEGER, NUMERIC…) |
| Deduplication | None | Business key UNIQUE constraint |
| Business rules | None applied | Applied (Yes/No→bool, year casting…) |
| Load strategy | TRUNCATE + INSERT | SCD Type 1 UPSERT |

## Workflow

1. **Identify the business key** — what combination of columns makes a row unique in the real world
2. **Choose column types** — see [COLUMN-TYPES.md](references/COLUMN-TYPES.md)
3. **Write the DDL** — see [DDL-PATTERNS.md](references/DDL-PATTERNS.md)
4. **Implement UPSERT** — see [UPSERT.md](references/UPSERT.md)

## Business Key Design Rules

- Use the source system's natural key when it exists (e.g., `aptiad_no` for FTAs)
- Include `record_source` when multiple systems contribute to the same table
- Keys must be stable over time — changing keys break UPSERT

**Examples from this project:**

| Table | Business Key | Rationale |
|-------|-------------|-----------|
| `ods.trade_transaction` | `(year, month, hs_code, partner_code, flow_type, record_source)` | One record per period + product + partner + direction + source |
| `ods.fta` | `aptiad_no` | APTIAD's own unique integer ID |

## Key Rules

- Surrogate key: always `UUID DEFAULT gen_random_uuid()`, never `SERIAL`
- Always include `created_at TIMESTAMPTZ` and `updated_at TIMESTAMPTZ`
- `updated_at = NOW()` in the `DO UPDATE SET` clause
- Use `psycopg2.extras.execute_values` for bulk UPSERT — `df.to_sql()` does not support `ON CONFLICT`
