"""
ETL Pipeline Orchestrator

Runs the full Hybrid Inmon-Kimball ETL pipeline in strict phase order:

  Phase 01  — Extract
    01a. Pull trade flows + metadata from VPS1 mock API → stg.*
    01b. Read raw CSV/Excel files from mounted /raw_data  → stg.*

  Phase 02  — Cleanse & Transform
    02a. stg.* → ods.*                      (type cast, dedup, watermark)
    02b. ods.* → nds.* (3NF)               (fuzzy match, FK resolution)
    02c. Late-arriving data reprocessor     (reprocesses is_late_arriving rows)

  Phase 03  — Load to DDS (Star Schema)
    03a. nds.* → dds.* (SCD1/SCD2 dims + fact upsert)

Each phase is independently importable and runnable for debugging.
The orchestrator shares a single batch_id across all phases for full lineage.

Exit codes:
  0  — all phases succeeded
  1  — one or more phases failed (see stderr / logs for details)
"""

from __future__ import annotations

import sys
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from common.logging_config import setup_logging
from common.db import get_engine, register_batch, complete_batch

import importlib

# Phase modules loaded by string so each can also be run standalone
PHASES = [
    ("01_extract.extract_trademap_api",                "Phase 01a: Extract API"),
    ("01_extract.extract_raw_files",                   "Phase 01b: Extract Files"),
    ("02_cleansing_and_transform.staging_to_ods",      "Phase 02a: Staging → ODS"),
    ("02_cleansing_and_transform.staging_to_nds",      "Phase 02b: ODS → NDS"),
    ("02_cleansing_and_transform.late_arriving_handler","Phase 02c: Late-Arriving"),
    ("03_load_to_dds.nds_to_dds_scd",                 "Phase 03:  NDS → DDS SCD"),
]


def main() -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level, service="run_pipeline")
    logger = logging.getLogger("run_pipeline")

    pipeline_batch_id = register_batch(
        get_engine(cfg),
        f"full_pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
    logger.info("=" * 60)
    logger.info("Pipeline started  batch_id=%s", pipeline_batch_id)
    logger.info("=" * 60)

    engine = get_engine(cfg)
    failed_phases: list[str] = []

    for module_path, label in PHASES:
        logger.info("--- %s ---", label)
        try:
            mod = importlib.import_module(module_path)
            mod.run(batch_id=pipeline_batch_id)
            logger.info("    %s  SUCCEEDED", label)
        except Exception as exc:
            logger.error("    %s  FAILED: %s", label, exc)
            failed_phases.append(label)
            # Continue to next phase rather than aborting the entire pipeline.
            # Comment out the 'continue' below if strict fail-fast is preferred.
            continue

    logger.info("=" * 60)
    if failed_phases:
        logger.error("Pipeline finished with errors in phases: %s", failed_phases)
        complete_batch(
            engine, pipeline_batch_id,
            status="FAILED",
            error_message=f"Failed phases: {failed_phases}",
        )
        return 1

    complete_batch(engine, pipeline_batch_id, status="SUCCESS")
    logger.info("Pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
