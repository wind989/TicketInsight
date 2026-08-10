"""Runtime settings loaded from local environment variables only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Keep P0 configuration small and avoid embedding credentials in source."""

    app_env: str
    database_url: str
    sql_max_rows: int
    sql_timeout_seconds: int


@lru_cache
def get_settings() -> Settings:
    """Read the local .env once; later phases keep secrets in this process only."""

    load_dotenv(override=False)
    return Settings(
        app_env=os.getenv("TICKETINSIGHT_APP_ENV", "development"),
        database_url=os.getenv(
            "TICKETINSIGHT_DATABASE_URL",
            "mysql+pymysql://ticketinsight_user:CHANGE_ME@127.0.0.1:3306/ticketinsight",
        ),
        sql_max_rows=int(os.getenv("TICKETINSIGHT_SQL_MAX_ROWS", "200")),
        sql_timeout_seconds=int(os.getenv("TICKETINSIGHT_SQL_TIMEOUT_SECONDS", "5")),
    )


def get_migration_database_url() -> str:
    """Read the DDL-capable URL only inside Alembic; the FastAPI runtime never calls this function."""

    load_dotenv(override=False)
    database_url = os.getenv("TICKETINSIGHT_MIGRATION_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TICKETINSIGHT_MIGRATION_DATABASE_URL 未配置，拒绝执行迁移")
    return database_url


def get_readonly_database_url() -> str:
    """Return the future P2 read-only connection only for the deterministic SQL executor."""

    load_dotenv(override=False)
    database_url = os.getenv("TICKETINSIGHT_READONLY_DATABASE_URL")
    if not database_url:
        raise RuntimeError("TICKETINSIGHT_READONLY_DATABASE_URL 未配置，拒绝执行分析 SQL")
    return database_url


def get_llm_timeout_seconds() -> float:
    """Bound one model HTTP call so an unavailable provider cannot leave a run permanently running."""

    load_dotenv(override=False)
    try:
        timeout_seconds = float(os.getenv("TICKETINSIGHT_LLM_TIMEOUT_SECONDS", "20"))
    except ValueError as error:
        raise RuntimeError("TICKETINSIGHT_LLM_TIMEOUT_SECONDS must be a number between 1 and 60") from error
    if not 1 <= timeout_seconds <= 60:
        raise RuntimeError("TICKETINSIGHT_LLM_TIMEOUT_SECONDS must be between 1 and 60")
    return timeout_seconds
