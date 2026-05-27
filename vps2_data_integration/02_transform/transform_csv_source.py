"""
Transform extracted UN Comtrade CSV data before loading into staging.

Responsibilities:
  - Rename columns from UN Comtrade camelCase to snake_case (staging DDL naming)
  - Cast numeric columns to float (source CSV may encode values as bool/string)
  - Read from tmp/trade_extracted.csv, write to tmp/trade_transformed.csv

Entry point:
  run() -> pd.DataFrame
    Returns the transformed DataFrame. Saves result to tmp/trade_transformed.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def run() -> pd.DataFrame:
    tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
    input_file = tmp_dir / "trade_extracted.csv"
    output_file = tmp_dir / "trade_transformed.csv"

    df = pd.read_csv(input_file, dtype=str)

    df = df.rename(columns=COLUMN_RENAME_MAP)

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.to_csv(output_file, index=False)
    return df


if __name__ == "__main__":
    df = run()
    print(f"Transformed {len(df)} rows → tmp/trade_transformed.csv")
