"""Deterministic execution of SQL accepted by the AST gate, using the dedicated read-only connection only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_readonly_database_url, get_settings
from app.services.sql_safety import ValidatedSQL, validate_readonly_select


class ReadonlyQueryExecutionError(RuntimeError):
    """Expose only a stable, non-sensitive execution failure to callers and logs."""


@dataclass(frozen=True)
class QueryResult:
    """Bounded rows and neutral metadata for analysis; no query response body is logged automatically."""

    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: int
    executed_sql: str
    audit_sql: str
    tables: tuple[str, ...]


def build_readonly_engine() -> Engine:
    """Create an engine exclusively from the P2 read-only URL, never the migration or CRUD URL."""

    settings = get_settings()
    return create_engine(
        get_readonly_database_url(),
        future=True,
        pool_pre_ping=True,
        connect_args={"read_timeout": settings.sql_timeout_seconds, "write_timeout": settings.sql_timeout_seconds},
    )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _mysql_execution_sql(validated: ValidatedSQL, dialect_name: str, timeout_seconds: int) -> str:
    """Add a deterministic MySQL time hint after validation, leaving user/model SQL comment-free."""

    if dialect_name != "mysql":
        return validated.sql
    timeout_ms = max(1, timeout_seconds) * 1000
    return validated.sql.replace("SELECT ", f"SELECT /*+ MAX_EXECUTION_TIME({timeout_ms}) */ ", 1)


class ReadonlyQueryExecutor:
    """Run one validated SELECT with SQL-level LIMIT plus MySQL server-side execution-time hint."""

    def __init__(self, engine: Engine, *, max_rows: int | None = None, timeout_seconds: int | None = None) -> None:
        settings = get_settings()
        self.engine = engine
        self.max_rows = max_rows if max_rows is not None else settings.sql_max_rows
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.sql_timeout_seconds

    def execute(self, candidate_sql: str) -> QueryResult:
        """Validate immediately before execution, then fetch no more rows than the gate allowed."""

        validated = validate_readonly_select(candidate_sql, max_rows=self.max_rows)
        execution_sql = _mysql_execution_sql(validated, self.engine.dialect.name, self.timeout_seconds)
        started_at = perf_counter()
        try:
            with self.engine.connect() as connection:
                result = connection.execution_options(stream_results=True).execute(text(execution_sql))
                rows = [
                    {key: _serialize_value(value) for key, value in row._mapping.items()}
                    for row in result.fetchmany(validated.max_rows)
                ]
        except SQLAlchemyError as error:
            raise ReadonlyQueryExecutionError(f"只读查询执行失败：{type(error).__name__}") from error
        return QueryResult(
            rows=rows,
            row_count=len(rows),
            duration_ms=round((perf_counter() - started_at) * 1000),
            executed_sql=execution_sql,
            audit_sql=validated.audit_sql,
            tables=validated.tables,
        )
