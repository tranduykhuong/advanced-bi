"""
Transform extracted Trade Map CSV before loading into stage.stage_db.

Responsibilities:
  - Text normalization (mojibake fix for country/product labels)
  - Derive period (YYYYMM) from year + month
  - Cast numeric columns via pd.to_numeric(errors="coerce")
  - Read from tmp/trademap_extracted.csv, write to tmp/trademap_transformed.csv

Entry point:
  run() -> pd.DataFrame
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def run() -> pd.DataFrame:
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    input_file = tmp_dir / "trademap_extracted.csv"
    output_file = tmp_dir / "trademap_transformed.csv"

    df = pd.read_csv(input_file, dtype=str)

    for col in ("exporter_name", "importer_name", "product_label"):
        if col in df.columns:
            df[col] = df[col].map(_normalize_trademap_text)

    df["product_code"] = df["product_code"].str.strip().str.lstrip("'")

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    before_drop = len(df)
    df = df.dropna(subset=["year", "month", "exporter_name", "importer_name"])
    dropped = before_drop - len(df)
    if dropped:
        print(f"Dropped {dropped} rows with NULL year/month or country names")

    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["period"] = (
        df["year"].astype(str).str.zfill(4) + df["month"].astype(str).str.zfill(2)
    )

    df = df[list(OUTPUT_COLUMNS)]
    df.to_csv(output_file, index=False)
    return df


if __name__ == "__main__":
    df = run()
    print(f"Transformed {len(df)} rows → tmp/trademap_transformed.csv")
