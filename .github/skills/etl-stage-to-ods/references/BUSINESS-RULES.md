# Business Rules — Helper Functions

## Yes/No → BOOLEAN

```python
def to_bool(val) -> bool | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    v = str(val).strip().lower()
    if v == "yes":
        return True
    if v == "no":
        return False
    return None
```

## Year String → INTEGER

```python
import re

def to_year(val) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    v = str(val).strip()
    if re.fullmatch(r"\d{4}", v):
        return int(v)
    return None
```

## Controlled Vocabulary Normalization

```python
STATUS_MAP = {
    "entry into force": "Entry into Force",
    "under negotiation": "Under Negotiation",
    "terminated": "Terminated",
    "signed & pending ratification": "Signed & Pending ratification",
}

SCOPE_MAP = {
    "bilateral": "Bilateral",
    "country - bloc": "Country - Bloc",
    "plurilateral": "Plurilateral",
    "bloc - bloc": "Bloc - Bloc",
}

def normalize_label(val, mapping: dict[str, str]) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    cleaned = " ".join(str(val).split())
    if not cleaned:
        return None
    return mapping.get(cleaned.lower(), cleaned)  # fallback: keep original
```

## Semicolon-Separated → List

```python
def parse_members(members_raw) -> list[str]:
    if members_raw is None or (isinstance(members_raw, float) and pd.isna(members_raw)):
        return []
    parts = [m.strip() for m in str(members_raw).split(";") if m.strip()]
    return list(dict.fromkeys(parts))  # deduplicate, preserve order
```

## HS Code → Chapter + Heading

```python
def parse_hs_code(hs) -> tuple[str, str, str, str]:
    """Return (hs_code_6, chapter_2, heading_4, hs_code_6)"""
    if pd.isna(hs) or not str(hs).strip():
        return "", "00", "0000", ""
    hs_str = str(hs).strip().zfill(6)[:6]
    return hs_str, hs_str[:2], hs_str[:4], hs_str
```

## Quality Flags

```python
df["quality_flags"] = [[] for _ in range(len(df))]

df.loc[df["value"].fillna(0) <= 0, "quality_flags"] = df.loc[
    df["value"].fillna(0) <= 0, "quality_flags"
].apply(lambda x: x + ["INVALID_VALUE"])

# Filter out unusable rows
df = df[df["value"].fillna(0) > 0].reset_index(drop=True)
```

## Chunked Transform (Large Files)

```python
from common.chunking import DEFAULT_CHUNK_SIZE

output_file = tmp_dir / "transformed.csv"
if output_file.exists():
    output_file.unlink()

first_chunk = True
total_rows = 0
for chunk in pd.read_csv(input_file, chunksize=DEFAULT_CHUNK_SIZE, low_memory=False):
    chunk = apply_business_rules(chunk)
    chunk.to_csv(output_file, mode="w" if first_chunk else "a", header=first_chunk, index=False)
    total_rows += len(chunk)
    first_chunk = False
```
