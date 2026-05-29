"""
ETL Pipeline Orchestrator

Runs the full Hybrid Inmon-Kimball ETL pipeline in strict phase order.

Phase Structure:
  01_Extract → 02_Transform → 03_Load
"""

from __future__ import annotations

import sys
import importlib
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from common.logging_config import setup_logging
from common.db import get_engine, register_batch, complete_batch

PHASES = [
    # ETL CSV → Stage
    ("01_extract.extract_csv", "Phase 01: Extract CSV (UN Comtrade)"),
    ("02_transform.transform_csv_source", "Phase 02: Transform CSV → Stage"),
    ("03_load.load_stage_csv", "Phase 03: Load stage_csv"),
    # ETL TXT → Stage
    ("01_extract.extract_txt_files", "Phase 01: Extract TXT (NSO)"),
    ("02_transform.transform_text_source", "Phase 02: Transform TXT → Stage"),
    ("03_load.load_stage_text", "Phase 03: Load stage_text"),
    # ETL Stage → ODS
    ("01_extract.extract_stage", "Phase 01: Extract from Stage"),
    ("02_transform.stage_to_ods", "Phase 02: Stage → ODS (Transform + BR)"),
    # ("02_transform.late_arriving_handler", "Phase 02: Late-Arriving Handler"),
    ("03_load.stage_to_ods", "Phase 03: Load into ODS (UPSERT)"),
    # ETL ODS → NDS
    ("02_transform.ods_to_nds", "Phase 02: ODS → NDS (3NF)"),
    # ETL NDS → DDS
    ("03_load.nds_to_dds_scd", "Phase 03: NDS → DDS (SCD)"),
]


def main() -> int:
    cfg = load_config()
    setup_logging(level=cfg.log_level, service="run_pipeline")
    logger = logging.getLogger("run_pipeline")
    engine = get_engine(cfg)

    pipeline_batch_id = register_batch(
        engine,
        f"full_pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    )
    logger.info("Pipeline started | batch_id=%s", pipeline_batch_id)

    failed_phases: list[str] = []

    for module_path, label in PHASES:
        logger.info("--- %s ---", label)
        try:
            mod = importlib.import_module(module_path)
            mod.run(batch_id=pipeline_batch_id)
            logger.info("    %s  OK", label)
        except NotImplementedError:
            logger.warning("    %s  SKIPPED (not yet implemented)", label)
        except ModuleNotFoundError:
            logger.warning("    %s  SKIPPED (module not found)", label)
        except Exception as exc:
            logger.error("    %s  FAILED: %s", label, exc)
            failed_phases.append(label)

    if failed_phases:
        logger.error("Pipeline finished with errors in: %s", failed_phases)
        complete_batch(
            engine, pipeline_batch_id, status="FAILED", error_message=str(failed_phases)
        )
        return 1

    complete_batch(engine, pipeline_batch_id, status="SUCCESS")
    logger.info("✅ Pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
