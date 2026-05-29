from __future__ import annotations

import sys
import uuid
import pandas as pd
import csv
from pathlib import Path

import country_converter as coco
import pycountry
from rapidfuzz import process, fuzz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch
from common.chunking import DEFAULT_CHUNK_SIZE

logger = get_logger(__name__)


EXPECTED_COLS = [
    "year",
    "quarter",
    "month",
    "hs_code",
    "category_chapter",
    "category_heading",
    "product_name",
    "partner_code",
    "partner_name",
    "partner_region",
    "partner_continent",
    "fta_keys",
    "flow_type",
    "value",
    "quantity",
    "unit",
    "record_source",
    "source_system",
    "batch_id",
    "is_late_arriving",
    "quality_flags",
]

cc = coco.CountryConverter()

COUNTRY_NAMES = [c.name for c in pycountry.countries]
COUNTRY_ALIASES = {
    "MYANMA": "Myanmar",
    "MEHICO": "Mexico",
    "BRAXIN": "Brazil",
    "HUNGARI": "Hungary",
    "ACHENTINA": "Argentina",
    "PHILIPIN": "Philippines",
    "NIGIERIA": "Nigeria",
    "UCRAINA": "Ukraine",
}
NAME_TO_ALPHA3 = {c.name.upper(): c.alpha_3 for c in pycountry.countries}
ALPHA3_TO_META = {
    c.alpha_3: {
        "name": c.name,
        "continent": cc.convert(names=c.alpha_3, to="continent"),
        "region": cc.convert(names=c.alpha_3, to="UNregion"),
    }
    for c in pycountry.countries
}


def resolve_from_country_name(name: str):
    country = str(name).strip()
    country = COUNTRY_ALIASES.get(country.upper(), country)

    code = NAME_TO_ALPHA3.get(country.upper())
    if code:
        meta = ALPHA3_TO_META.get(code)
        return code, meta["region"], meta["continent"], country

    try:
        iso3 = cc.convert(names=country, to="ISO3")
        if iso3 and iso3 != "not found":
            meta = ALPHA3_TO_META.get(iso3)
            return iso3, meta["region"], meta["continent"], country
    except:
        pass

    match = process.extractOne(country, COUNTRY_NAMES, scorer=fuzz.WRatio)
    if match and match[1] > 70:
        best = match[0]
        code = NAME_TO_ALPHA3.get(best.upper())
        meta = ALPHA3_TO_META.get(code)
        return code, meta["region"], meta["continent"], country

    return None, None, None, country


def resolve_from_country_code(code):
    code_str = str(code).strip().upper()
    meta = ALPHA3_TO_META.get(code_str)
    if meta:
        return meta["name"], meta["region"], meta["continent"]
    return None, None, None


def parse_hs_code(hs):
    if pd.isna(hs) or not str(hs).strip():
        return "", "00", "0000", ""

    hs_str = str(hs).strip().zfill(6)[:6]
    return hs_str, hs_str[:2], hs_str[:4], hs_str


def calculate_quarter(month):
    return ((month - 1) // 3) + 1 if pd.notna(month) else None


def apply_business_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["quality_flags"] = [[] for _ in range(len(df))]

    df.loc[df["value"].fillna(0) <= 0, "quality_flags"] = df.loc[
        df["value"].fillna(0) <= 0, "quality_flags"
    ].apply(lambda x: x + ["INVALID_VALUE"])

    original_product_name = df["product_name"].copy()
    df[["hs_code", "category_chapter", "category_heading", "product_name"]] = df[
        "hs_code"
    ].apply(lambda x: pd.Series(parse_hs_code(x)))
    # Restore descriptive product names (e.g. from Trade Map product_label) that
    # parse_hs_code would have overwritten with the raw HS string.
    has_description = original_product_name.notna() & (original_product_name.astype(str).str.strip() != "")
    df.loc[has_description, "product_name"] = original_product_name[has_description]

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    mask_code = df["partner_code"].notna()

    if mask_code.any():
        resolved_code = df.loc[mask_code, "partner_code"].apply(
            lambda x: pd.Series(resolve_from_country_code(x))
        )
        df.loc[mask_code, "partner_name"] = resolved_code[0].values
        df.loc[mask_code, "partner_region"] = resolved_code[1].values
        df.loc[mask_code, "partner_continent"] = resolved_code[2].values

    mask_name = ~mask_code
    if mask_name.any():
        resolved_name = df.loc[mask_name, "partner_name"].apply(
            lambda x: pd.Series(resolve_from_country_name(x))
        )
        df.loc[mask_name, "partner_code"] = resolved_name[0].values
        df.loc[mask_name, "partner_region"] = resolved_name[1].values
        df.loc[mask_name, "partner_continent"] = resolved_name[2].values
        df.loc[mask_name, "partner_name"] = resolved_name[3].values

    df["quarter"] = df["month"].apply(calculate_quarter)

    before = len(df)
    df = df[df["value"].fillna(0) > 0].reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        logger.info("Dropped %d rows with value <= 0", dropped)

    return df


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "stage_to_ods")

    total_rows = 0
    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "stage_extracted.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        output_file = tmp_dir / "stage_to_ods_transformed.csv"
        if output_file.exists():
            output_file.unlink()

        first_chunk = True
        for chunk in pd.read_csv(
            input_file,
            chunksize=DEFAULT_CHUNK_SIZE,
            low_memory=False,
            dtype={"hs_code": str},
        ):
            chunk = apply_business_rules(chunk)

            for c in EXPECTED_COLS:
                if c not in chunk.columns:
                    if c in ["quality_flags", "fta_keys"]:
                        chunk[c] = [[] for _ in range(len(chunk))]
                    else:
                        chunk[c] = None

            chunk = chunk[EXPECTED_COLS]

            chunk.to_csv(
                output_file,
                mode="w" if first_chunk else "a",
                header=first_chunk,
                index=False,
                encoding="utf-8",
                quoting=csv.QUOTE_NONNUMERIC,
                quotechar='"',
            )

            total_rows += len(chunk)
            first_chunk = False

        logger.info("Transform completed: %s rows → %s", total_rows, output_file)

    except Exception as exc:
        logger.exception("stage_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)

    return total_rows


if __name__ == "__main__":
    run()
