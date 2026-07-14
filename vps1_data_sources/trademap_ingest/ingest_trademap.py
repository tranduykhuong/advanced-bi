"""
Ingest ITC Trade Map CSV exports into VPS1 PostgreSQL (country, product, trade_record).

Run manually on VPS1 (not part of CI/CD). Example:

    cd vps1_data_sources/trademap_ingest
    pip install -r requirements.txt
    export VPS1_DB_HOST=localhost VPS1_DB_PORT=5432 ...
    python ingest_trademap.py --data-dir ../raw_data
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import os
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import config

logger = logging.getLogger(__name__)

DATA_AVAILABILITY_FILE = "Trade_Map_-_Data_Availability.csv"
PRODUCTS_FILE = (
    "Trade_Map_-_List_of_exported_products_for_the_selected_product_(All_products).csv"
)

COUNTRY_SKIP_ROWS = 7
PRODUCT_SKIP_ROWS = 8

EXPORTER_COLUMNS = ("Exporters", "Exporter")
IMPORTER_COLUMNS = ("Importers", "Importer")
PRODUCT_COLUMNS = ("Product code", "Product Code", "HS code")

VALUE_COL_PATTERN = re.compile(r"value in", re.IGNORECASE)
PERIOD_PATTERN = re.compile(r"(\d{4})-M(\d{2})")
BILATERAL_FILE_PATTERN = re.compile(
    r"Bilateral_trade_between_(.+)_and_(.+)\.csv$", re.IGNORECASE
)
BILATERAL_TITLE_PATTERN = re.compile(
    r"Bilateral trade between\s+(.+?)\s+and\s+(.+?)\s*,*\s*$", re.IGNORECASE
)
# Bilateral files in this project are related to Viet Nam.
TARGET_COUNTRY = "Viet Nam"

# Trade Map CSV exports are often Windows-1252 or Latin-1, not UTF-8.
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
TRADE_FILE_SUFFIXES = (".csv")

UPSERT_TRADE_SQL = text("""
    WITH exp AS (SELECT id FROM country WHERE name = :exporter_name LIMIT 1),
         imp AS (SELECT id FROM country WHERE name = :importer_name LIMIT 1)
    INSERT INTO trade_record (exporter_id, importer_id, product_code, year, month, value_usd_k)
    SELECT exp.id, imp.id, :product_code, :year, :month, :value
    FROM exp, imp
    WHERE exp.id IS NOT NULL AND imp.id IS NOT NULL
    ON CONFLICT (exporter_id, importer_id, product_code, year, month)
    DO UPDATE SET value_usd_k = EXCLUDED.value_usd_k
""")


def get_engine() -> Engine:
    return create_engine(config.get_sqlalchemy_url(), pool_pre_ping=True)


def _clean_product_code(raw: object) -> str:
    return str(raw).strip().lstrip("'")


def _normalize_trademap_text(value: object) -> str:
    """Fix common mojibake in Trade Map Latin-1 / Windows exports."""
    text = str(value).strip()
    # 0x99 in Latin-1 exports often stands in for ô (e.g. Côte d'Ivoire).
    return text.replace("\x99", "ô").replace("™", "ô")


def _ensure_countries(conn, names: Iterable[str]) -> int:
    """Insert missing countries (e.g. Türkiye may be absent from Data_Availability)."""
    added = 0
    seen: set[str] = set()
    for name in names:
        normalized = _normalize_trademap_text(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result = conn.execute(
            text(
                "INSERT INTO country (name) VALUES (:name) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {"name": normalized},
        )
        added += result.rowcount or 0
    return added


def _read_trademap_csv(path: Path | str, **kwargs) -> pd.DataFrame:
    """Read a Trade Map CSV, trying common legacy encodings before Latin-1."""
    path = Path(path)
    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding, **kwargs)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path, encoding="latin-1", **kwargs)


def _open_trademap_text(path: Path | str):
    """Open a Trade Map CSV as text with the same encoding fallback as read_csv."""
    path = Path(path)
    for encoding in CSV_ENCODINGS:
        try:
            fh = open(path, encoding=encoding)
            fh.read(4096)
            fh.seek(0)
            return fh
        except UnicodeDecodeError:
            continue
    return open(path, encoding="latin-1")


def _find_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    cols_lower = {c.lower(): c for c in df.columns}
    for name in candidates:
        if name in df.columns:
            return name
        if name.lower() in cols_lower:
            return cols_lower[name.lower()]
    return None


def _infer_bilateral_pair(path: Path) -> tuple[str | None, str | None]:
    file_match = BILATERAL_FILE_PATTERN.search(path.name)
    if file_match:
        exporter = file_match.group(1).replace("_", " ").strip()
        importer = file_match.group(2).replace("_", " ").strip()
        return exporter, importer

    with _open_trademap_text(path) as fh:
        for _ in range(15):
            line = fh.readline()
            if not line:
                break
            title = line.split(",", 1)[0].strip()
            title_match = BILATERAL_TITLE_PATTERN.match(title)
            if title_match:
                return title_match.group(1).strip(), title_match.group(2).strip()

    return None, None


def _load_bilateral_data(
    path: Path,
    skip_rows: int,
    target_country: str = TARGET_COUNTRY,
    trade_flow: str = "import",
) -> pd.DataFrame:
    """
    Parse bilateral Trade Map CSV with 2-row header.
    If trade_flow == 'import': keeps "<Partner>'s exports to <Target>"
    If trade_flow == 'export': keeps "<Target>'s exports to <Partner>"
    """
    preview = _read_trademap_csv(path, skiprows=skip_rows, nrows=2, header=None)
    if preview.shape[0] < 2:
        raise ValueError(f"Expected 2 header rows after skiprows in {path}")

    header_top_raw = preview.iloc[0].fillna("").astype(str).tolist()
    header_sub = preview.iloc[1].fillna("").astype(str).tolist()
    header_top: list[str] = []
    current_group = ""
    for cell in header_top_raw:
        value = cell.strip()
        if value:
            current_group = value
        header_top.append(current_group)

    c1, c2 = _infer_bilateral_pair(path)
    if not c1 or not c2:
        raise ValueError(f"Could not infer countries from bilateral file: {path}")

    partner = c1 if c2.lower() == target_country.lower() else c2
    if c1.lower() != target_country.lower() and c2.lower() != target_country.lower():
        partner = c1

    if trade_flow == "import":
        exporter_name = partner
        importer_name = target_country
        target_phrases = [
            f"exports to {target_country}".lower(),
            f"imports from {partner}".lower(),
        ]
    else:
        exporter_name = target_country
        importer_name = partner
        target_phrases = [
            f"exports to {partner}".lower(),
            f"imports from {target_country}".lower(),
        ]

    product_code_idx = next(
        (i for i, c in enumerate(header_top) if c.strip().lower() == "product code"),
        None,
    )
    if product_code_idx is None:
        raise KeyError(f"Could not find 'Product code' in {path}")

    export_value_idxs = []
    for i, (top, sub) in enumerate(zip(header_top, header_sub)):
        top_norm = _normalize_trademap_text(top).lower()
        sub_norm = str(sub).strip()
        if any(phrase in top_norm for phrase in target_phrases) and PERIOD_PATTERN.search(sub_norm):
            export_value_idxs.append(i)

    if not export_value_idxs:
        raise ValueError(
            f"Could not find monthly columns matching {target_phrases} in {path}"
        )

    data = _read_trademap_csv(path, skiprows=skip_rows + 2, header=None)

    rows: list[dict[str, object]] = []
    for _, row in data.iterrows():
        raw_code = row.iloc[product_code_idx] if product_code_idx < len(row) else None
        if pd.isna(raw_code):
            continue
        product_code = _clean_product_code(raw_code)
        if not product_code:
            continue

        for col_idx in export_value_idxs:
            if col_idx >= len(row):
                continue
            period_label = str(header_sub[col_idx]).strip()
            match = PERIOD_PATTERN.search(period_label)
            if not match:
                continue
            year = int(match.group(1))
            month = int(match.group(2))
            value = pd.to_numeric(row.iloc[col_idx], errors="coerce")
            if pd.isna(value):
                continue

            rows.append(
                {
                    "exporter_name": _normalize_trademap_text(exporter_name or ""),
                    "importer_name": _normalize_trademap_text(importer_name or ""),
                    "product_code": product_code,
                    "year": year,
                    "month": month,
                    "value_usd_k": float(value),
                }
            )

    if not exporter_name or not importer_name:
        raise ValueError(f"Could not infer countries from bilateral file: {path}")

    return pd.DataFrame(rows)


def _detect_skip_rows(file_path: Path, header_markers: tuple[str, ...]) -> int:
    with _open_trademap_text(file_path) as fh:
        for i, line in enumerate(fh):
            if any(marker in line for marker in header_markers):
                return i
    raise ValueError(
        f"Could not detect header row in {file_path}. "
        f"Expected one of: {header_markers}"
    )


def _collect_trade_files_from_dir(trade_dir: Path) -> list[Path]:
    """Collect trade files in a folder (csv/xls/xlsx), sorted by filename."""
    if not trade_dir.exists():
        raise FileNotFoundError(f"Trade directory not found: {trade_dir}")
    if not trade_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {trade_dir}")

    files = [
        p
        for p in trade_dir.iterdir()
        if p.is_file() and p.suffix.lower() in TRADE_FILE_SUFFIXES
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def init_master_data(
    engine: Engine | None = None,
    data_dir: Path | str = ".",
) -> None:
    """Load countries and products from Trade Map reference CSVs."""
    engine = engine or get_engine()
    base = Path(data_dir)
    print("Starting to load master data...")

    country_path = base / DATA_AVAILABILITY_FILE
    product_path = base / PRODUCTS_FILE

    print(f"Country path: {country_path}")
    print(f"Product path: {product_path}")

    if not country_path.exists():
        raise FileNotFoundError(country_path)
    if not product_path.exists():
        raise FileNotFoundError(product_path)

    df_country = _read_trademap_csv(country_path, skiprows=COUNTRY_SKIP_ROWS)
    country_col = _find_column(df_country, ("Countries and Territories",))
    if not country_col:
        raise KeyError(
            f"'Countries and Territories' column not found in {country_path}"
        )

    countries = (
        df_country[country_col]
        .dropna()
        .map(_normalize_trademap_text)
        .unique()
        .tolist()
    )
    if "World" not in countries:
        countries.append("World")

    df_product = _read_trademap_csv(product_path, skiprows=PRODUCT_SKIP_ROWS)
    code_col = _find_column(df_product, ("Product code",))
    label_col = _find_column(df_product, ("Product label",))
    if not code_col or not label_col:
        raise KeyError(f"Product code/label columns not found in {product_path}")

    df_product = df_product[[code_col, label_col]].dropna()

    with engine.begin() as conn:
        _ensure_countries(conn, countries)

        for _, row in df_product.iterrows():
            print(f"Inserting product: {row[code_col]} {row[label_col]}")
            conn.execute(
                text(
                    "INSERT INTO product (code, label) VALUES (:code, :label) "
                    "ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label"
                ),
                {
                    "code": _clean_product_code(row[code_col]),
                    "label": _normalize_trademap_text(row[label_col]),
                },
            )

    logger.info(
        "Master data loaded: %d countries, %d products",
        len(countries),
        len(df_product),
    )


def process_trade_file(
    file_path: str | Path,
    default_exporter: str | None = None,
    default_importer: str | None = None,
    default_product: str | None = None,
    *,
    skip_rows: int | None = None,
    engine: Engine | None = None,
    batch_size: int = 1000,
    trade_flow: str = "import",
) -> int:
    """Read a Trade Map CSV, melt monthly columns, upsert into trade_record."""
    engine = engine or get_engine()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(path)

    print(f"Processing file: {path}")

    if skip_rows is None:
        skip_rows = _detect_skip_rows(
            path,
            EXPORTER_COLUMNS + IMPORTER_COLUMNS + PRODUCT_COLUMNS + ("Exported value",),
        )

    is_bilateral_file = "Bilateral_trade_between_" in path.name
    if is_bilateral_file:
        df_long = _load_bilateral_data(path=path, skip_rows=skip_rows, trade_flow=trade_flow)
    else:
        df = _read_trademap_csv(path, skiprows=skip_rows)
        value_cols = [c for c in df.columns if VALUE_COL_PATTERN.search(str(c))]
        if not value_cols:
            raise ValueError(f"No 'Exported value in YYYY-Mxx' columns found in {path}")

        exporter_col = _find_column(df, EXPORTER_COLUMNS)
        importer_col = _find_column(df, IMPORTER_COLUMNS)
        product_col = _find_column(df, PRODUCT_COLUMNS)

        print(f"Exporter column: {exporter_col}")
        print(f"Importer column: {importer_col}")
        print(f"Product column: {product_col}")

        id_vars: list[str] = []
        if exporter_col and not default_exporter:
            id_vars.append(exporter_col)
        if importer_col and not default_importer:
            id_vars.append(importer_col)
        if product_col and not default_product:
            id_vars.append(product_col)

        df_long = df.melt(
            id_vars=id_vars or None,
            value_vars=value_cols,
            var_name="period",
            value_name="value_usd_k",
        )

        extracted = df_long["period"].astype(str).str.extract(PERIOD_PATTERN)
        df_long["year"] = pd.to_numeric(extracted[0], errors="coerce").astype("Int64")
        df_long["month"] = pd.to_numeric(extracted[1], errors="coerce").astype("Int64")
        df_long["value_usd_k"] = pd.to_numeric(df_long["value_usd_k"], errors="coerce")

        df_long = df_long.dropna(subset=["year", "month", "value_usd_k"])
        df_long["year"] = df_long["year"].astype(int)
        df_long["month"] = df_long["month"].astype(int)

        if default_exporter:
            df_long["exporter_name"] = default_exporter
        elif exporter_col:
            df_long["exporter_name"] = df_long[exporter_col].map(_normalize_trademap_text)
        else:
            raise ValueError("default_exporter is required when file has no exporter column")

        if default_importer:
            df_long["importer_name"] = default_importer
        elif importer_col:
            df_long["importer_name"] = df_long[importer_col].map(_normalize_trademap_text)
        else:
            raise ValueError("default_importer is required when file has no importer column")

        if default_product:
            df_long["product_code"] = default_product
        elif product_col:
            df_long["product_code"] = df_long[product_col].map(_clean_product_code)
        else:
            raise ValueError("default_product is required when file has no product column")

    records = [
        {
            "exporter_name": row["exporter_name"],
            "importer_name": row["importer_name"],
            "product_code": row["product_code"],
            "year": int(row["year"]),
            "month": int(row["month"]),
            "value": float(row["value_usd_k"]),
        }
        for _, row in df_long.iterrows()
    ]

    if not records:
        logger.warning("No trade rows to load from %s", path)
        return 0

    country_names: list[str] = []
    if is_bilateral_file:
        country_names = df_long["exporter_name"].drop_duplicates().tolist() + df_long["importer_name"].drop_duplicates().tolist()
    else:
        if default_exporter:
            country_names.append(default_exporter)
        if default_importer:
            country_names.append(default_importer)

    inserted_total = 0
    with engine.begin() as conn:
        if country_names:
            added = _ensure_countries(conn, country_names)
            if added:
                logger.info("Added %d new countries before trade load", added)

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            result = conn.execute(UPSERT_TRADE_SQL, batch)
            inserted_total += result.rowcount or 0

    skipped = len(records) - inserted_total
    if inserted_total == 0:
        logger.error(
            "No trade rows were written to trade_record from %s "
            "(parsed %d rows; check country/product master data)",
            path,
            len(records),
        )
    elif skipped:
        logger.warning(
            "Skipped %d/%d parsed rows from %s (missing FK targets or conflicts)",
            skipped,
            len(records),
            path,
        )

    logger.info(
        "Upserted %d trade rows from %s (%d parsed)",
        inserted_total,
        path,
        len(records),
    )
    return inserted_total


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest ITC Trade Map CSVs into VPS1 PostgreSQL"
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("RAW_DATA_PATH", "/raw_data"),
        help="Directory containing Trade Map CSV files",
    )
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="Skip loading country/product reference files",
    )
    parser.add_argument(
        "--trade-dir",
        default=None,
        help=(
            "Directory containing trade files to ingest "
            "(all *.csv/*.xls/*.xlsx inside will be processed)"
        ),
    )
    parser.add_argument(
        "--trade-flow",
        choices=["import", "export"],
        default="import",
        help="Direction of bilateral trade data ('import' or 'export')",
    )
    parser.add_argument(
        "trade_files",
        nargs="*",
        help="Optional trade CSV paths to process after master data load",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    data_dir = Path(args.data_dir)
    engine = get_engine()
    print(f"Engine: {engine}")
    print(f"Data dir: {data_dir}")
    print(f"Skip master: {args.skip_master}")
    print(f"Trade files: {args.trade_files}")
    print(f"Trade dir: {args.trade_dir}")

    if not args.skip_master:
        init_master_data(engine=engine, data_dir=data_dir)

    trade_inputs: list[Path | str] = []
    if args.trade_files:
        trade_inputs = args.trade_files
    elif args.trade_dir:
        trade_dir = Path(args.trade_dir)
        if not trade_dir.is_absolute():
            trade_dir = data_dir / trade_dir
        trade_inputs = _collect_trade_files_from_dir(trade_dir)
        logger.info("Discovered %d trade files in %s", len(trade_inputs), trade_dir)

    if trade_inputs:
        trade_flow = args.trade_flow
        if args.trade_dir and trade_flow == "import":
            if "export" in Path(args.trade_dir).name.lower():
                trade_flow = "export"
        
        for fp in trade_inputs:
            process_trade_file(fp, engine=engine, trade_flow=trade_flow)
        return

    if not args.skip_master and not args.trade_files:
        examples = [
            (
                data_dir / "Trade_Map_-_List_of_exporters_for_the_selected_product_.csv",
                {"default_importer": "World", "default_product": "TOTAL"},
            ),
            (
                data_dir
                / "Trade_Map_-_List_of_importing_markets_for_a_product_exported_by_China.csv",
                {"default_exporter": "China", "default_product": "TOTAL"},
            ),
        ]
        for path, kwargs in examples:
            if path.exists():
                process_trade_file(path, **kwargs, engine=engine)
            else:
                logger.info("Skipping missing example file: %s", path)


if __name__ == "__main__":
    main(sys.argv[1:])
