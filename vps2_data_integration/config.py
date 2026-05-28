"""
Central configuration module — reads all settings from environment variables.
No secrets or IPs are hard-coded here; defaults are safe for local Docker Compose.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass

DOCKER_VPS1_HOST = "postgres_vps1"


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def dsn(self) -> str:
        """psycopg2-compatible DSN string."""
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


@dataclass(frozen=True)
class Vps1DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


@dataclass(frozen=True)
class AppConfig:
    db: DatabaseConfig
    vps1_db: Vps1DatabaseConfig
    vps1_api_url: str
    raw_data_path: str
    app_env: str
    log_level: str


def _host_resolves(hostname: str) -> bool:
    try:
        socket.getaddrinfo(hostname, None)
        return True
    except socket.gaierror:
        return False


def _resolve_vps1_db_endpoint() -> tuple[str, int]:
    """Resolve VPS1 DB host/port for ETL extract (inside or outside Docker)."""
    configured_host = (
        os.getenv("VPS1_DB_HOST")
        or os.getenv("TRADEMAP_DB_HOST")
        or DOCKER_VPS1_HOST
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

    if configured_host == DOCKER_VPS1_HOST and not _host_resolves(configured_host):
        return "localhost", mapped_port

    return configured_host, internal_port


def load_config() -> AppConfig:
    """Build AppConfig from environment. Raises ValueError for missing required vars."""
    password = os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError(
            "DB_PASSWORD (or POSTGRES_PASSWORD) environment variable is required."
        )

    vps1_password = (
        os.getenv("VPS1_DB_PASSWORD")
        or os.getenv("VPS1_POSTGRES_PASSWORD")
        or os.getenv("TRADEMAP_DB_PASSWORD")
    )
    if not vps1_password:
        raise ValueError(
            "VPS1_DB_PASSWORD or VPS1_POSTGRES_PASSWORD environment variable is required."
        )

    vps1_host, vps1_port = _resolve_vps1_db_endpoint()

    return AppConfig(
        db=DatabaseConfig(
            host=os.getenv("DB_HOST", "postgres_dw"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "bi_dw"),
            user=os.getenv("DB_USER", "bi_admin"),
            password=password,
        ),
        vps1_db=Vps1DatabaseConfig(
            host=vps1_host,
            port=vps1_port,
            name=os.getenv(
                "VPS1_POSTGRES_DB",
                os.getenv("TRADEMAP_DB_NAME", "trademap_db"),
            ),
            user=os.getenv(
                "VPS1_DB_USER",
                os.getenv("VPS1_POSTGRES_USER", os.getenv("TRADEMAP_DB_USER", "trademap_admin")),
            ),
            password=vps1_password,
        ),
        vps1_api_url=os.getenv("VPS1_API_URL", "http://mock_api:8000"),
        raw_data_path=os.getenv("RAW_DATA_PATH", "/raw_data"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
