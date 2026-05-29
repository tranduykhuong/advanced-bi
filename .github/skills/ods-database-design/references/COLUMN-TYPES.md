# ODS Column Type Reference

| Data Type | Use | Example Columns |
|-----------|-----|-----------------|
| `BOOLEAN` | Yes/No flags, has_X indicators | `has_trade_goods`, `is_upgraded`, `provision_sps_tbt`, `flow_type` |
| `INTEGER` | Years, counts | `year_signature`, `year_enforcement`, `aptiad_no` |
| `SMALLINT` | Month (1–12), quarter (1–4) | `month`, `quarter` |
| `NUMERIC(18,6)` | Trade values, quantities with decimals | `value`, `quantity` |
| `VARCHAR(3)` | ISO 3-letter country codes | `partner_code` |
| `VARCHAR(n)` | Bounded controlled vocabulary | `status VARCHAR(80)`, `scope VARCHAR(80)` |
| `TEXT` | Unbounded strings | `product_name`, `fta_name`, `source_link` |
| `TEXT[]` | Multi-value arrays | `member_countries`, `fta_keys`, `quality_flags` |
| `UUID` | Surrogate keys, batch references | `{entity}_id`, `batch_id` |
| `TIMESTAMPTZ` | Audit timestamps (always with timezone) | `created_at`, `updated_at` |
| `DATE` | Calendar dates without time | `snapshot_date` |

## Never Use in ODS

- `SERIAL` / `BIGSERIAL` → use `UUID DEFAULT gen_random_uuid()`
- `FLOAT` for monetary values → use `NUMERIC(18,6)` for exact precision
- `VARCHAR(n)` for unknown-length strings → use `TEXT`
