"""Structured JSON-style logging configuration shared across all ETL phases."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO", service: str = "etl_engine") -> logging.Logger:
    """Configure root logger with a structured format and return a named logger.

    Log lines include timestamp, level, service name, and message so they can
    be parsed by log aggregators (Loki, CloudWatch, etc.) without extra config.
    """
    fmt = (
        "%(asctime)s | %(levelname)-8s | "
        + service
        + " | %(name)s | %(message)s"
    )
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )
    return logging.getLogger(service)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger. Call setup_logging() once at startup first."""
    return logging.getLogger(name)
