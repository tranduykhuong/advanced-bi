from __future__ import annotations

import csv
import json
import re
from decimal import Decimal
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging, get_logger
from common.db import get_engine, register_batch, complete_batch

logger = get_logger(__name__)

MONTH_COLUMNS = 4


def _parse_decimal(value: str) -> Decimal | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if not cleaned:
        return None
    return Decimal(cleaned)


def _parse_month_rows(
    raw_values: list[str],
) -> list[tuple[int, Decimal | None, Decimal | None]]:
    nums = [_parse_decimal(value) for value in raw_values]
    nums = [n for n in nums if n is not None]
    rows: list[tuple[int, Decimal | None, Decimal | None]] = []

    if len(nums) >= MONTH_COLUMNS:
        if len(nums) == 5:
            for month_index, value in enumerate(nums[:MONTH_COLUMNS], start=1):
                rows.append((month_index, None, value * Decimal(1000)))
            return rows

        if len(nums) == 10:
            for month_index in range(MONTH_COLUMNS):
                quantity = nums[month_index * 2]
                value = nums[month_index * 2 + 1]
                rows.append((month_index + 1, quantity, value * Decimal(1000)))
            return rows

        if len(nums) == 8:
            for month_index in range(MONTH_COLUMNS):
                quantity = nums[month_index * 2]
                value = nums[month_index * 2 + 1]
                rows.append((month_index + 1, quantity, value * Decimal(1000)))
            return rows

        for month_index, value in enumerate(nums[:MONTH_COLUMNS], start=1):
            rows.append((month_index, None, value * Decimal(1000)))
        return rows

    raise ValueError(f"Unexpected raw_values length {len(raw_values)}: {raw_values}")


def _transform_record(record: dict) -> list[dict]:
    goods = record["goods"]
    country = record["country"]
    flow_type = record["flow_type"]
    year = record["year"]
    source_file = record["source_file"]
    raw_values = record["raw_values"]

    month_rows: list[dict] = []
    for month, quantity, value in _parse_month_rows(raw_values):
        if value is None:
            continue

        month_rows.append(
            {
                "country": country,
                "goods": goods,
                "flow_type": flow_type,
                "quantity": str(quantity) if quantity is not None else "",
                "value": str(value),
                "month": month,
                "year": year,
            }
        )

    return month_rows


def run(batch_id: uuid.UUID | None = None) -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    engine = get_engine(cfg)

    managed_batch = batch_id is None
    if managed_batch:
        batch_id = register_batch(engine, "transform_text_source")

    try:
        tmp_dir = Path(__file__).resolve().parents[1] / "tmp"
        input_file = tmp_dir / "text_source_extracted.jsonl"
        output_file = tmp_dir / "stage_text_transformed.csv"

        if not input_file.exists():
            raise FileNotFoundError(f"Extracted artifact not found: {input_file}")

        rows_written = 0
        with input_file.open("r", encoding="utf-8") as in_fp, output_file.open(
            "w", encoding="utf-8", newline=""
        ) as out_fp:
            writer = csv.writer(out_fp)
            writer.writerow(
                ["country", "goods", "flow_type", "quantity", "value", "month", "year"]
            )

            for raw_line in in_fp:
                record = json.loads(raw_line)
                for normalized in _transform_record(record):
                    writer.writerow(
                        [
                            normalized["country"],
                            normalized["goods"],
                            "TRUE" if normalized["flow_type"] else "FALSE",
                            normalized["quantity"],
                            normalized["value"],
                            normalized["month"],
                            normalized["year"],
                        ]
                    )
                    rows_written += 1

        logger.info("Wrote transformed stage rows to %s", output_file)
    except Exception as exc:
        logger.exception("transform_text_source failed: %s", exc)
        if managed_batch:
            complete_batch(engine, batch_id, status="FAILED", error_message=str(exc))
        raise

    if managed_batch:
        complete_batch(engine, batch_id, rows_loaded=rows_written)
    return rows_written


if __name__ == "__main__":
    run()
