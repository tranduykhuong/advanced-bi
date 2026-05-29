"""
ETL Pipeline Orchestrator

Runs the full Hybrid Inmon-Kimball ETL pipeline in strict phase order.
Each phase runs in a separate subprocess so memory is fully released between steps.

Exit codes:
  0  — all phases succeeded
  1  — one or more phases failed (check logs for details)

Usage:
  python run_pipeline.py                              # full pipeline
  python run_pipeline.py --phase extract-stage        # one CI/CD phase group
  python run_pipeline.py --phase stage-ods --batch-id <uuid> --finalize
  python -m common.run_module 01_extract.extract_csv  # single module
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import load_config
from common.logging_config import setup_logging
from common.db import batch_exists, get_engine, register_batch, complete_batch

PHASES = [
    # ETL APTIAD → Stage
    ("01_extract.extract_aptiad", "Phase 01: Extract APTIAD FTA"),
    ("02_transform.transform_aptiad_source", "Phase 02: Transform APTIAD → Stage"),
    ("03_load.load_stage_aptiad", "Phase 03: Load stage_aptiad"),
    # ETL CSV → Stage
    ("01_extract.extract_csv", "Phase 01: Extract CSV (UN Comtrade)"),
    ("02_transform.transform_csv_source", "Phase 02: Transform CSV → Stage"),
    ("03_load.load_stage_csv", "Phase 03: Load stage_csv"),
    # ETL TXT → Stage
    ("01_extract.extract_txt_files", "Phase 01: Extract TXT (NSO)"),
    ("02_transform.transform_text_source", "Phase 02: Transform TXT → Stage"),
    ("03_load.load_stage_text", "Phase 03: Load stage_text"),
    # ETL DB → Stage
    ("01_extract.extract_trademap", "Phase 01: Extract Trade Map (VPS1)"),
    ("03_load.load_stage_db", "Phase 03: Load stage_db"),

    # ETL Stage → ODS (FTA)
    ("01_extract.extract_stage_aptiad", "Phase 01: Extract stage_aptiad"),
    ("02_transform.fta_stage_to_ods", "Phase 02: FTA Stage → ODS (Transform)"),
    ("03_load.load_fta_to_ods", "Phase 03: Load ods.fta"),
    # ETL Stage → ODS (Trade)
    ("01_extract.extract_stage", "Phase 01: Extract from Stage"),
    ("02_transform.stage_to_ods", "Phase 02: Stage → ODS (Transform + BR)"),
    # ("02_transform.late_arriving_handler", "Phase 02: Late-Arriving Handler"),
    ("03_load.stage_to_ods", "Phase 03: Load into ODS (UPSERT)"),

    # ETL ODS → NDS
    ("02_transform.ods_to_nds", "Phase 02: ODS → NDS (3NF)"),
    # ETL NDS → DDS
    ("03_load.nds_to_dds_scd", "Phase 03: NDS → DDS (SCD)"),
]

PHASE_GROUPS: dict[str, list[tuple[str, str]]] = {
    "extract-stage": PHASES[:11],
    "stage-ods": PHASES[11:17],
    "ods-nds": PHASES[17:18],
    "nds-dds": PHASES[18:19],
}

PHASE_GROUP_LABELS: dict[str, str] = {
    "extract-stage": "Extract & Load Stage",
    "stage-ods": "Stage → ODS",
    "ods-nds": "ODS → NDS",
    "nds-dds": "NDS → DDS",
}

APP_ROOT = Path(__file__).resolve().parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BI DW ETL pipeline.")
    parser.add_argument(
        "--phase",
        choices=["all", *PHASE_GROUPS.keys()],
        default="all",
        help="Phase group to run (default: all).",
    )
    parser.add_argument(
        "--batch-id",
        help="Reuse an existing pipeline batch UUID across CI/CD jobs.",
    )
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Mark the pipeline batch SUCCESS/FAILED after this run.",
    )
    return parser.parse_args()


def _resolve_batch_id(args: argparse.Namespace) -> uuid.UUID | None:
    raw = args.batch_id or os.getenv("ETL_BATCH_ID")
    if not raw:
        return None
    return uuid.UUID(raw)


def _select_phases(phase: str) -> list[tuple[str, str]]:
    if phase == "all":
        return PHASES
    return PHASE_GROUPS[phase]


def _run_phase(module_path: str, batch_id: str) -> int:
    env = os.environ.copy()
    env["ETL_BATCH_ID"] = batch_id
    return subprocess.run(
        [sys.executable, "-m", "common.run_module", module_path],
        env=env,
        cwd=APP_ROOT,
        check=False,
    ).returncode


def _ensure_batch(
    engine,
    *,
    batch_id: uuid.UUID | None,
    phase: str,
) -> uuid.UUID:
    if batch_id is None:
        suffix = phase if phase != "all" else "full"
        return register_batch(
            engine,
            f"pipeline_{suffix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        )

    if batch_exists(engine, batch_id):
        return batch_id

    return register_batch(
        engine,
        f"pipeline_cicd_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        batch_id=batch_id,
    )


def main() -> int:
    args = _parse_args()
    cfg = load_config()
    setup_logging(level=cfg.log_level, service="run_pipeline")
    logger = logging.getLogger("run_pipeline")
    engine = get_engine(cfg)

    phases = _select_phases(args.phase)
    requested_batch_id = _resolve_batch_id(args)
    pipeline_batch_id = _ensure_batch(
        engine,
        batch_id=requested_batch_id,
        phase=args.phase,
    )
    batch_id_str = str(pipeline_batch_id)
    group_label = PHASE_GROUP_LABELS.get(args.phase, "Full pipeline")

    logger.info(
        "Pipeline started  batch_id=%s  phase=%s  group=%s",
        pipeline_batch_id,
        args.phase,
        group_label,
    )
    print(f"ETL_BATCH_ID={batch_id_str}", flush=True)

    failed_phases: list[str] = []

    for module_path, label in phases:
        logger.info("--- %s ---", label)
        exit_code = _run_phase(module_path, batch_id_str)
        if exit_code == 2:
            logger.warning("    %s  SKIPPED (not yet implemented)", label)
        elif exit_code != 0:
            logger.error("    %s  FAILED (exit code %d)", label, exit_code)
            failed_phases.append(label)
        else:
            logger.info("    %s  OK", label)

    should_finalize = args.finalize or args.phase == "all"
    if failed_phases:
        logger.error("Pipeline finished with errors in: %s", failed_phases)
        if should_finalize:
            complete_batch(
                engine,
                pipeline_batch_id,
                status="FAILED",
                error_message=str(failed_phases),
            )
        return 1

    if should_finalize:
        complete_batch(engine, pipeline_batch_id, status="SUCCESS")
    logger.info("✅ Pipeline phase group completed successfully: %s", group_label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
