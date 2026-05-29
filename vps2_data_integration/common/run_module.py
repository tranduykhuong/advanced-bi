"""
Run a single ETL phase module in an isolated process.

Usage:
  ETL_BATCH_ID=<uuid> python -m common.run_module 01_extract.extract_trademap

Exit codes:
  0 — success
  1 — failure
  2 — skipped (NotImplementedError)
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config
from common.logging_config import setup_logging


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m common.run_module <module.path>", file=sys.stderr)
        return 1

    cfg = load_config()
    setup_logging(level=cfg.log_level)
    logger = logging.getLogger("run_module")

    batch_id: uuid.UUID | None = None
    raw_batch_id = os.getenv("ETL_BATCH_ID")
    if raw_batch_id:
        batch_id = uuid.UUID(raw_batch_id)

    module_path = sys.argv[1]
    try:
        mod = importlib.import_module(module_path)
        mod.run(batch_id=batch_id)
    except NotImplementedError as exc:
        logger.warning("SKIPPED (%s): %s", module_path, exc)
        return 2
    except Exception:
        logger.exception("Phase failed: %s", module_path)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
