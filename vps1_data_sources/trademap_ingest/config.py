"""
PostgreSQL connection settings for Trade Map ingestion on VPS1.

Uses VPS1_* / TRADEMAP_* environment variables (separate from VPS3 warehouse DB).
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DOCKER_SERVICE_HOST = "postgres_vps1"

# Repository root .env (two levels up from this file)
_repo_root = Path(__file__).resolve().parents[2]
_env_file = _repo_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
else:
    load_dotenv()


def _host_resolves(hostname: str) -> bool:
    try:
        socket.getaddrinfo(hostname, None)
        return True
    except socket.gaierror:
        return False


def _resolve_db_endpoint() -> tuple[str, int]:
    """
    Resolve DB host/port for manual ingest.

    - Inside Docker Compose: postgres_vps1:5432
    - On host against mapped container port: localhost + VPS1_POSTGRES_PORT (5433)
    """
    configured_host = (
        os.getenv("VPS1_DB_HOST")
        or os.getenv("TRADEMAP_DB_HOST")
        or DOCKER_SERVICE_HOST
    )
    mapped_port = int(os.getenv("VPS1_POSTGRES_PORT", "5433"))
    internal_port = int(
        os.getenv("VPS1_DB_PORT") or os.getenv("TRADEMAP_DB_PORT") or "5432"
    )

    if configured_host in ("localhost", "127.0.0.1"):
        port = int(
            os.getenv("VPS1_DB_PORT")
            or os.getenv("TRADEMAP_DB_PORT")
            or str(mapped_port)
        )
        return configured_host, port

    if configured_host == DOCKER_SERVICE_HOST and not _host_resolves(configured_host):
        logger.info(
            "Host %s not reachable outside Docker; using localhost:%s",
            configured_host,
            mapped_port,
        )
        return "localhost", mapped_port

    return configured_host, internal_port


host, port = _resolve_db_endpoint()
user: str = os.getenv(
    "VPS1_DB_USER",
    os.getenv("VPS1_POSTGRES_USER", os.getenv("TRADEMAP_DB_USER", "trademap_admin")),
)
password: str | None = (
    os.getenv("VPS1_DB_PASSWORD")
    or os.getenv("VPS1_POSTGRES_PASSWORD")
    or os.getenv("TRADEMAP_DB_PASSWORD")
)
dbname: str = os.getenv(
    "VPS1_POSTGRES_DB",
    os.getenv("TRADEMAP_DB_NAME", "trademap_db"),
)


def get_sqlalchemy_url() -> str:
    """Build a SQLAlchemy URL for psycopg (v3)."""
    if not password:
        raise ValueError(
            "VPS1_DB_PASSWORD or VPS1_POSTGRES_PASSWORD environment variable is required."
        )
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"
