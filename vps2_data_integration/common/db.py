"""Database connection helpers shared across all ETL phases."""

from __future__ import annotations

import json
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


def get_vps1_engine(cfg: AppConfig) -> Engine:
    """Create a SQLAlchemy engine for the VPS1 Trade Map source database."""
    return create_engine(cfg.vps1_db.sqlalchemy_url, pool_pre_ping=True)


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


def batch_exists(engine: Engine, batch_id: uuid.UUID) -> bool:
    """Return True if batch_id is already present in etl_batch_log."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM public.etl_batch_log WHERE batch_id = :bid"),
            {"bid": str(batch_id)},
        ).first()
    return row is not None


def register_batch(
    engine: Engine,
    batch_name: str,
    batch_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a new row into public.etl_batch_log and return the batch UUID."""
    resolved_batch_id = batch_id or uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.etl_batch_log (batch_id, batch_name, status) "
                "VALUES (:bid, :name, 'RUNNING')"
            ),
            {"bid": str(resolved_batch_id), "name": batch_name},
        )
    logger.info(
        "Registered batch batch_id=%s name=%s", resolved_batch_id, batch_name
    )
    return resolved_batch_id


def complete_batch(
    engine: Engine,
    batch_id: uuid.UUID,
    rows_extracted: int = 0,
    rows_loaded: int = 0,
    rows_rejected: int = 0,
    rows_upserted: int = 0,
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
                "    rows_rejected = :rrej, rows_upserted = :rups, "
                "    error_message = :err "
                "WHERE batch_id = :bid"
            ),
            {
                "bid": str(batch_id),
                "status": status,
                "rext": rows_extracted,
                "rl": rows_loaded,
                "rrej": rows_rejected,
                "rups": rows_upserted,
                "err": error_message,
            },
        )
    logger.info(
        "Batch completed batch_id=%s status=%s rows_extracted=%d rows_loaded=%d "
        "rows_rejected=%d rows_upserted=%d",
        batch_id, status, rows_extracted, rows_loaded, rows_rejected, rows_upserted,
    )


def log_reject_records(
    engine: Engine,
    batch_id: uuid.UUID,
    process_type: int,
    source_table: str,
    reject_reason: str,
    rows: list[dict],
) -> int:
    """Bulk-insert excluded/invalid rows into public.reject_records for audit
    and data-lineage traceability.

    process_type: 1 = Stage->ODS, 2 = ODS->NDS, 3 = NDS->DDS.
    rows: JSON-serializable dicts, one per rejected record.
    Returns the number of rows inserted (0 if ``rows`` is empty).
    """
    if not rows:
        return 0
    payload = [
        {
            "batch_id": str(batch_id),
            "process_type": process_type,
            "source_table": source_table,
            "reject_reason": reject_reason,
            "row_data": json.dumps(row, default=str),
        }
        for row in rows
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.reject_records "
                "(batch_id, process_type, source_table, reject_reason, row_data) "
                "VALUES (:batch_id, :process_type, :source_table, :reject_reason, "
                "        CAST(:row_data AS JSONB))"
            ),
            payload,
        )
    logger.warning(
        "Logged %d reject_records (process_type=%d, source_table=%s, reason=%s)",
        len(payload), process_type, source_table, reject_reason,
    )
    return len(payload)


def log_late_arrival_audit(
    engine: Engine,
    batch_id: uuid.UUID,
    source_table: str,
    rows: list[dict],
) -> int:
    """Permanently record newly-detected late-arriving business keys, once, at
    detection time — independent of the mutable is_late_arriving flag lifecycle
    (which gets cleared once propagation to NDS is verified). Used for historical
    late-arrival-rate analysis (see 04_mining/risk_trade_balance_prediction.py).
    """
    if not rows:
        return 0
    payload = [
        {"batch_id": str(batch_id), "source_table": source_table, **row}
        for row in rows
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.late_arrival_audit "
                "(batch_id, source_table, year, month, hs_code, partner_code, flow_type, source_system) "
                "VALUES (:batch_id, :source_table, :year, :month, :hs_code, :partner_code, :flow_type, :source_system)"
            ),
            payload,
        )
    logger.info(
        "Logged %d late_arrival_audit row(s) (source_table=%s)",
        len(payload), source_table,
    )
    return len(payload)
