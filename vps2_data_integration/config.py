"""
Central configuration module — reads all settings from environment variables.
No secrets or IPs are hard-coded here; defaults are safe for local Docker Compose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
class AppConfig:
    db: DatabaseConfig
    vps1_api_url: str
    raw_data_path: str
    app_env: str
    log_level: str


def load_config() -> AppConfig:
    """Build AppConfig from environment. Raises ValueError for missing required vars."""
    password = os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError(
            "DB_PASSWORD (or POSTGRES_PASSWORD) environment variable is required."
        )

    return AppConfig(
        db=DatabaseConfig(
            host=os.getenv("DB_HOST", "postgres_dw"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "bi_dw"),
            user=os.getenv("DB_USER", "bi_admin"),
            password=password,
        ),
        vps1_api_url=os.getenv("VPS1_API_URL", "http://mock_api:8000"),
        raw_data_path=os.getenv("RAW_DATA_PATH", "/raw_data"),
        app_env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
