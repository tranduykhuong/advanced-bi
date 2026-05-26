"""Database connection helpers shared across all ETL phases."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import AppConfig

logger = logging.getLogger(__name__)


def get_engine(cfg: AppConfig) -> Engine:
    """Create and return a SQLAlchemy engine with a connection pool."""
    engine = create_engine(
        cfg.db.sqlalchemy_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    return engine


@contextmanager
def get_psycopg2_conn(cfg: AppConfig) -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a raw psycopg2 connection with autocommit disabled.

    Use for bulk COPY operations or when you need fine-grained transaction control.
    The connection is always closed on exit.
    """
    conn = psycopg2.connect(cfg.db.dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def register_batch(engine: Engine, batch_name: str) -> uuid.UUID:
    """Insert a new row into public.etl_batch_log and return the batch UUID."""
    batch_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.etl_batch_log (batch_id, batch_name, status) "
                "VALUES (:bid, :name, 'RUNNING')"
            ),
            {"bid": str(batch_id), "name": batch_name},
        )
    logger.info("Registered batch batch_id=%s name=%s", batch_id, batch_name)
    return batch_id


def complete_batch(
    engine: Engine,
    batch_id: uuid.UUID,
    rows_extracted: int = 0,
    rows_loaded: int = 0,
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> None:
    """Update etl_batch_log on completion or failure."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.etl_batch_log "
                "SET finished_at = NOW(), status = :status, "
                "    rows_extracted = :rext, rows_loaded = :rl, "
                "    error_message = :err "
                "WHERE batch_id = :bid"
            ),
            {
                "bid": str(batch_id),
                "status": status,
                "rext": rows_extracted,
                "rl": rows_loaded,
                "err": error_message,
            },
        )
    logger.info(
        "Batch completed batch_id=%s status=%s rows_extracted=%d rows_loaded=%d",
        batch_id, status, rows_extracted, rows_loaded,
    )
