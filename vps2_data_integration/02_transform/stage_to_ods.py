from __future__ import annotations

import sys
import uuid
import pandas as pd
import csv
import re

from pathlib import Path

import country_converter as coco
import pycountry

from rapidfuzz import process, fuzz

from sklearn.feature_extraction.text import (
    TfidfVectorizer,
)
from sklearn.metrics.pairwise import (
    cosine_similarity,
)

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]),
)

from config import load_config
from common.logging_config import (
    setup_logging,
    get_logger,
)
from common.db import (
    get_engine,
    register_batch,
    complete_batch,
)

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

# ==================== RULE-BASED MAPPING (ĐÃ SỬA - TOÀN BỘ 6 CHỮ SỐ) ====================

RULE_BASED_MAP = {
    # Soybeans
    "soybean": "120190",
    "soybeans": "120190",
    # Cassava
    "casava": "071410",
    "cassava": "071410",
    # Seafood / Fish
    "seafood": "030399",
    "fish": "030399",
    "shrimp": "030617",
    "prawn": "030617",
    # Chemicals (general)
    "chemicals": "380300",
    # Motor vehicles
    "motor vehicle": "870390",
    "motor vehicles": "870390",
    "vehicles": "870390",
    # Plastic materials
    "plastic": "392690",
    # Rattan & Bamboo
    "rattan": "940383",
    "bamboo": "940382",
    # Animal fodder / feed
    "animal fodder": "230990",
    # Pottery & Glassware
    "pottery": "691200",
    # Crude oil
    "crude oil": "270900",
}


# ==================== HS CACHE ====================

_HS_MAP = None

# ==================== TF-IDF CACHE ====================

_HS_VECTORIZER = None
_HS_MATRIX = None
_HS_CODES = None


# ==================== TEXT NORMALIZATION ====================


def normalize_product_text(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


# ==================== RULE BASED INFERENCE ====================


def apply_rule_based_inference(product_name: str) -> str | None:
    if pd.isna(product_name) or not str(product_name).strip():
        return None

    normalized = normalize_product_text(product_name)
    for keyword, hs_code in RULE_BASED_MAP.items():
        if keyword in normalized:
            logger.debug(f"Rule-based match: '{product_name}' → {hs_code}")
            return hs_code
    return None


# ==================== HS MAP ====================


def load_hs_map():
    global _HS_MAP
    if _HS_MAP is not None:
        return _HS_MAP

    cfg = load_config()
    hs_file = Path(cfg.raw_data_path) / "harmonized-system.csv"

    if not hs_file.exists():
        logger.warning(f"HS file not found: {hs_file}")
        _HS_MAP = {}
        return _HS_MAP

    try:
        df_hs = pd.read_csv(hs_file, dtype=str, low_memory=False)
        _HS_MAP = {}

        for _, row in df_hs.iterrows():
            hscode = str(row["hscode"]).strip().zfill(6)[:6]
            description = str(row["description"]).strip()
            level = int(row["level"]) if pd.notna(row["level"]) else 0

            if hscode not in _HS_MAP:
                _HS_MAP[hscode] = {"description": description, "level": level}

        logger.info("Loaded %s HS codes into memory", len(_HS_MAP))
    except Exception as e:
        logger.error(f"Failed to load HS map: {e}")
        _HS_MAP = {}

    return _HS_MAP


# ==================== TF-IDF INDEX ====================


def load_hs_vector_index():
    global _HS_VECTORIZER, _HS_MATRIX, _HS_CODES
    if _HS_MATRIX is not None:
        return

    hs_map = load_hs_map()
    rows = []

    for hs_code, meta in hs_map.items():
        if meta["level"] != 6:
            continue
        desc = normalize_product_text(meta["description"])
        if desc:
            rows.append((hs_code, desc))

    _HS_CODES = [x[0] for x in rows]
    descriptions = [x[1] for x in rows]

    logger.info("Building TF-IDF index...")
    _HS_VECTORIZER = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    _HS_MATRIX = _HS_VECTORIZER.fit_transform(descriptions)

    logger.info("TF-IDF index ready: %s entries", len(_HS_CODES))


# ==================== HS INFERENCE ====================


def infer_hs_codes_batch(product_names):
    load_hs_vector_index()
    texts = [normalize_product_text(x) for x in product_names.fillna("").astype(str)]
    predictions = []

    for text in texts:
        # 1. Rule-based (ưu tiên)
        rule_hs = apply_rule_based_inference(text)
        if rule_hs:
            predictions.append(rule_hs)
            continue

        # 2. TF-IDF
        query_matrix = _HS_VECTORIZER.transform([text])
        similarities = cosine_similarity(query_matrix, _HS_MATRIX)
        best_idx = similarities[0].argmax()
        best_score = float(similarities[0][best_idx])

        if best_score >= 0.2:
            predictions.append(_HS_CODES[best_idx])
        else:
            # 3. Fuzzy fallback
            all_desc = [
                meta["description"] for meta in _HS_MAP.values() if meta["level"] == 6
            ]
            best_match = process.extractOne(
                text, all_desc, scorer=fuzz.token_sort_ratio, score_cutoff=60
            )
            if best_match:
                for code, meta in _HS_MAP.items():
                    if meta["level"] == 6 and meta["description"] == best_match[0]:
                        predictions.append(code)
                        break
                else:
                    predictions.append(None)
            else:
                predictions.append(None)

    return predictions


# ==================== HS DESCRIPTION & RESOLUTION (giữ nguyên) ====================


def get_hs_description(hs_code: str):
    hs_map = load_hs_map()
    code = str(hs_code).strip().zfill(6)[:6]

    if code in hs_map:
        return hs_map[code]["description"]

    for i in range(4, 0, -2):
        short_code = code[:i].ljust(6, "0")
        if short_code in hs_map:
            return hs_map[short_code]["description"]
    return ""


def resolve_from_hs_code(hs):
    if pd.isna(hs) or not str(hs).strip():
        return "000000", "", "", ""

    hs_str = str(hs).strip().zfill(6)[:6]
    chapter_desc = get_hs_description(hs_str[:2])
    heading_desc = get_hs_description(hs_str[:4])
    product_desc = get_hs_description(hs_str)

    return hs_str, chapter_desc, heading_desc, product_desc


# ==================== COUNTRY FUNCTIONS (giữ nguyên) ====================


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
        return meta["region"], meta["continent"]
    return None, None


def calculate_quarter(month):
    return ((month - 1) // 3) + 1 if pd.notna(month) else None


# ==================== BUSINESS RULES ====================


def apply_business_rules(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["quality_flags"] = [[] for _ in range(len(df))]

    df.loc[df["value"].fillna(0) <= 0, "quality_flags"] = df.loc[
        df["value"].fillna(0) <= 0, "quality_flags"
    ].apply(lambda x: x + ["INVALID_VALUE"])

    # HS INFERENCE
    missing_hs_mask = df["hs_code"].isna() | (
        df["hs_code"].astype(str).str.strip() == ""
    )

    if missing_hs_mask.any():
        logger.info("Inferring HS codes for %s rows...", missing_hs_mask.sum())
        inferred_codes = infer_hs_codes_batch(df.loc[missing_hs_mask, "product_name"])
        df.loc[missing_hs_mask, "hs_code"] = inferred_codes

    # Resolve HS
    df[["hs_code", "category_chapter", "category_heading", "product_name"]] = df[
        "hs_code"
    ].apply(lambda x: pd.Series(resolve_from_hs_code(x)))

    # Numeric
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    # Partner
    mask_code = df["partner_code"].notna()
    if mask_code.any():
        resolved_code = df.loc[mask_code, "partner_code"].apply(
            lambda x: pd.Series(resolve_from_country_code(x))
        )
        df.loc[mask_code, "partner_region"] = resolved_code[0].values
        df.loc[mask_code, "partner_continent"] = resolved_code[1].values

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
    return df


# ==================== MAIN ====================


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "stage_to_ods")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "stage_extracted.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Missing file: {input_file}")

        df = pd.read_csv(input_file, low_memory=False, dtype={"hs_code": str})
        logger.info("Loaded %s rows from stage_extracted.csv", len(df))

        df = apply_business_rules(df)

        for c in EXPECTED_COLS:
            if c not in df.columns:
                if c in ["quality_flags", "fta_keys"]:
                    df[c] = [[] for _ in range(len(df))]
                else:
                    df[c] = None

        df = df[EXPECTED_COLS]

        output_file = tmp_dir / "stage_to_ods_transformed.csv"
        df.to_csv(
            output_file,
            index=False,
            encoding="utf-8",
            quoting=csv.QUOTE_NONNUMERIC,
            quotechar='"',
        )

        logger.info("Transform completed: %s rows → %s", len(df), output_file)

    except Exception as exc:
        logger.exception("stage_to_ods failed")
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=len(df))

    return len(df)


if __name__ == "__main__":
    run()
