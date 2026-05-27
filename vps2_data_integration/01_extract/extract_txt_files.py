from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch


def _normalize_text(value: str) -> str:
    return value.strip().strip('"')


def _normalize_number(value: str) -> str | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    return cleaned if cleaned else None


def extract_rows_from_text(text: str, source_file: str) -> list[dict]:
    lines = text.splitlines()
    if not lines:
        return []

    first_line = lines[0].strip()
    if "export" in first_line.lower():
        flow_type = True
    elif "import" in first_line.lower():
        flow_type = False
    else:
        raise ValueError(f"Unable to determine flow type from header: {first_line!r}")

    year_match = re.search(r"\b(20\d{2})\b", first_line)
    if not year_match:
        raise ValueError(f"Unable to determine year from header: {first_line!r}")
    year = int(year_match.group(1))

    month_count: int | None = None
    for line in lines[1:]:
        month_match = re.search(r"\b(\d+)\s+months?\b", line, re.IGNORECASE)
        if month_match:
            month_count = int(month_match.group(1))
            break
    if month_count is None:
        raise ValueError(
            "Unable to determine month count from header (expected 'N months')"
        )

    extracted: list[dict] = []
    current_goods: str | None = None

    for line in lines[1:]:
        if not line.strip():
            continue

        if line.strip().startswith("Goods"):
            continue
        if line.strip().lower().startswith("of which"):
            continue
        if "Quantity" in line or "Value" in line:
            continue

        fields = [field.strip() for field in line.split("\t")]
        if len(fields) < 3:
            continue

        goods_name = _normalize_text(fields[0]) if fields[0].strip() else None
        country_name = None
        if not goods_name and len(fields) > 1 and fields[1].strip():
            country_name = _normalize_text(fields[1])

        if goods_name:
            current_goods = goods_name
            continue

        if goods_name is None and country_name is None:
            continue
        if country_name and current_goods is None:
            continue

        numeric_fields = []
        for value in fields[2:]:
            if value and re.search(r"\d", value):
                normalized = _normalize_number(value)
                if normalized is not None:
                    numeric_fields.append(normalized)

        if not numeric_fields:
            continue

        extracted.append(
            {
                "source_file": source_file,
                "year": year,
                "flow_type": flow_type,
                "goods": current_goods if country_name else goods_name,
                "country": country_name,
                "raw_values": numeric_fields,
                "month_count": month_count,
            }
        )

    return extracted


logger = get_logger(__name__)


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "extract_txt_files")

    total_rows = 0
    try:
        raw_dir = Path(cfg.raw_data_path) / "text_source"
        if not raw_dir.exists():
            logger.warning("RAW_DATA_PATH '%s' not found — skipping.", raw_dir)
            if managed_batch:
                complete_batch(engine, batch_id, rows_loaded=0)
            return 0

        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        output_file = tmp_dir / "text_source_extracted.jsonl"

        with output_file.open("w", encoding="utf-8") as out_fp:
            for filepath in sorted(raw_dir.glob("*.txt")):
                logger.info("Extracting raw text file %s", filepath.name)
                text = filepath.read_bytes().decode("utf-16")
                source_rows = extract_rows_from_text(text, filepath.name)
                for row in source_rows:
                    out_fp.write(json.dumps(row, ensure_ascii=False))
                    out_fp.write("\n")
                total_rows += len(source_rows)

        logger.info("Wrote extracted raw text records to %s", output_file)
    except Exception as exc:
        logger.exception("extract_txt_files failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=total_rows)
    return total_rows


if __name__ == "__main__":
    run()
