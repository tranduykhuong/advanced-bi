"""
Transform extracted Trade Map CSV before loading into stage.stage_db.

Responsibilities:
  - Text normalization (mojibake fix for country/product labels)
  - Derive period (YYYYMM) from year + month
  - Cast numeric columns via pd.to_numeric(errors="coerce")
  - Read from tmp/trademap_extracted.csv, write to tmp/trademap_transformed.csv

Entry point:
  transform_to_file() -> int   (memory-bounded, used by pipeline)
  run() -> pd.DataFrame        (loads full file; for local debugging only)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common.chunking import DEFAULT_CHUNK_SIZE

OUTPUT_COLUMNS = (
    "exporter_name",
    "importer_name",
    "product_code",
    "product_label",
    "year",
    "month",
    "period",
    "value_usd_k",
)

NUMERIC_COLUMNS = ("year", "month", "value_usd_k")


def _normalize_trademap_text(value: object) -> str:
    """Fix common mojibake in Trade Map Latin-1 / Windows exports."""
    text = str(value).strip()
    return text.replace("\x99", "ô").replace("™", "ô")


def _transform_chunk(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("exporter_name", "importer_name", "product_label"):
        if col in df.columns:
            df[col] = df[col].map(_normalize_trademap_text)

    df["product_code"] = df["product_code"].str.strip().str.lstrip("'")

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["year", "month", "exporter_name", "importer_name"])
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["period"] = (
        df["year"].astype(str).str.zfill(4) + df["month"].astype(str).str.zfill(2)
    )

    return df[list(OUTPUT_COLUMNS)]


def transform_to_file(chunksize: int = DEFAULT_CHUNK_SIZE) -> int:
    """Transform extracted CSV in chunks. Returns total row count."""
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    input_file = tmp_dir / "trademap_extracted.csv"
    output_file = tmp_dir / "trademap_transformed.csv"

    if output_file.exists():
        output_file.unlink()

    total_rows = 0
    dropped_total = 0
    first_chunk = True

    for chunk in pd.read_csv(input_file, dtype=str, chunksize=chunksize):
        before_drop = len(chunk)
        transformed = _transform_chunk(chunk)
        dropped_total += before_drop - len(transformed)
        transformed.to_csv(
            output_file,
            mode="w" if first_chunk else "a",
            header=first_chunk,
            index=False,
        )
        total_rows += len(transformed)
        first_chunk = False

    if dropped_total:
        print(f"Dropped {dropped_total} rows with NULL year/month or country names")

    return total_rows


def run() -> pd.DataFrame:
    """Load and transform the full extracted file (for local debugging)."""
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    input_file = tmp_dir / "trademap_extracted.csv"
    output_file = tmp_dir / "trademap_transformed.csv"

    df = pd.read_csv(input_file, dtype=str)
    df = _transform_chunk(df)
    df.to_csv(output_file, index=False)
    return df


if __name__ == "__main__":
    row_count = transform_to_file()
    print(f"Transformed {row_count} rows → tmp/trademap_transformed.csv")
