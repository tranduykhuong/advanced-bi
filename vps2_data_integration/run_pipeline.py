"""
ETL Pipeline Orchestrator

Runs the full Hybrid Inmon-Kimball ETL pipeline in strict phase order.
Each phase runs in a separate subprocess so memory is fully released between steps.

Exit codes:
  0  — all phases succeeded
  1  — one or more phases failed (check logs for details)

Usage:
  python run_pipeline.py                     # full pipeline
  python -m common.run_module 01_extract.extract_csv  # single phase
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from common.logging_config import setup_logging
from common.db import get_engine, register_batch, complete_batch

PHASES = [
    ("01_extract.extract_api", "Phase 01: Extract API"),
    ("01_extract.extract_trademap", "Phase 01: Extract Trade Map (VPS1)"),
    ("01_extract.extract_txt_files", "Phase 01: Extract TXT Files"),
    ("01_extract.extract_csv", "Phase 01: Extract CSV Files"),
    ("02_transform.transform_text_source", "Phase 02: Transform TXT → Stage artifact"),
    ("02_transform.stage_to_ods", "Phase 02: Stage → ODS"),
    ("02_transform.ods_to_nds", "Phase 02: ODS → NDS"),
    ("02_transform.late_arriving_handler", "Phase 02: Late-Arriving"),
    ("03_load.load_stage_text", "Phase 03: Load stage_text"),
    ("03_load.load_stage_csv", "Phase 03: Load stage_csv"),
    ("03_load.load_stage_db", "Phase 03: Load stage_db"),
    ("03_load.nds_to_dds_scd", "Phase 03:  NDS → DDS SCD"),
]

APP_ROOT = Path(__file__).resolve().parent


def _run_phase(module_path: str, batch_id: str) -> int:
    env = os.environ.copy()
    env["ETL_BATCH_ID"] = batch_id
    return subprocess.run(
        [sys.executable, "-m", "common.run_module", module_path],
        env=env,
        cwd=APP_ROOT,
        check=False,
    ).returncode


def main() -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level, service="run_pipeline")
    logger = logging.getLogger("run_pipeline")
    engine = get_engine(cfg)

    pipeline_batch_id = register_batch(
        engine,
        f"full_pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
    batch_id_str = str(pipeline_batch_id)
    logger.info("Pipeline started  batch_id=%s", pipeline_batch_id)

    failed_phases: list[str] = []

    for module_path, label in PHASES:
        logger.info("--- %s ---", label)
        exit_code = _run_phase(module_path, batch_id_str)
        if exit_code == 2:
            logger.warning("    %s  SKIPPED (not yet implemented)", label)
        elif exit_code != 0:
            logger.error("    %s  FAILED (exit code %d)", label, exit_code)
            failed_phases.append(label)
        else:
            logger.info("    %s  OK", label)

    if failed_phases:
        logger.error("Pipeline finished with errors in: %s", failed_phases)
        complete_batch(
            engine, pipeline_batch_id, status="FAILED", error_message=str(failed_phases)
        )
        return 1

    complete_batch(engine, pipeline_batch_id, status="SUCCESS")
    logger.info("Pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
