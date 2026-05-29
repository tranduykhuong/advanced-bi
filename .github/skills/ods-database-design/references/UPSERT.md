# SCD Type 1 UPSERT Pattern

Use `psycopg2.extras.execute_values` for bulk UPSERT. `df.to_sql()` does not support `ON CONFLICT DO UPDATE`.

## Pattern

```python
from psycopg2.extras import execute_values

insert_cols = ["col_a", "col_b", "value", "batch_id", ...]
# Exclude immutable columns from the UPDATE SET
update_cols = [c for c in insert_cols if c not in ("natural_key", "source_system")]

records = [
    tuple(row[c] for c in insert_cols)
    for _, row in df.iterrows()
]

upsert_query = f"""
    INSERT INTO ods.{table} ({", ".join(insert_cols)})
    VALUES %s
    ON CONFLICT ({business_key_col}) DO UPDATE SET
        {", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)},
        updated_at = NOW()
"""

with engine.begin() as conn:
    raw_conn = conn.connection
    cursor = raw_conn.cursor()
    execute_values(cursor, upsert_query, records, page_size=500)
    raw_conn.commit()
```

## Handling Python Lists → PostgreSQL Arrays

`psycopg2` automatically converts Python `list` to PostgreSQL `TEXT[]`. Ensure list columns contain actual `list` objects (not strings):

```python
def _parse_list(val) -> list[str]:
    if isinstance(val, list):
        return val
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return []
    try:
        import ast
        parsed = ast.literal_eval(str(val).strip())
        if isinstance(parsed, list):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return [str(val)]

df["tags"] = df["tags"].apply(_parse_list)
```
