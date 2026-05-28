"""Shared chunk-size defaults for memory-bounded ETL steps."""

from __future__ import annotations

import os

DEFAULT_CHUNK_SIZE = int(os.getenv("ETL_CHUNK_SIZE", "10000"))
