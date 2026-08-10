"""P2 execution tests use SQLite only; no real MySQL credential or read-only account is required."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine

from app.models import Base, Customer, ProductModule, Ticket
from app.services.readonly_query import ReadonlyQueryExecutor
from app.services.sql_safety import SQLSafetyError


def test_executor_runs_only_gate_approved_rows_with_a_hard_limit():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(ProductModule.__table__.insert(), [{"name": "支付中心", "description": "合成模块", "status": "active"}])
        connection.execute(Customer.__table__.insert(), [{"anonymous_id": "anon-T001", "tier": "standard"}])
        connection.execute(
            Ticket.__table__.insert(),
            [
                {"title": "支付延迟", "body_redacted": "合成文本", "category": "payment", "priority": "high", "status": "open", "customer_id": 1, "module_id": 1, "created_at": datetime(2026, 8, 9, 10, tzinfo=timezone.utc)},
                {"title": "登录延迟", "body_redacted": "合成文本", "category": "login", "priority": "low", "status": "open", "customer_id": 1, "module_id": 1, "created_at": datetime(2026, 8, 9, 11, tzinfo=timezone.utc)},
            ],
        )

    result = ReadonlyQueryExecutor(engine, max_rows=1, timeout_seconds=2).execute(
        "SELECT category, priority FROM tickets ORDER BY id"
    )

    assert result.row_count == 1
    assert result.rows == [{"category": "payment", "priority": "high"}]
    assert result.executed_sql.endswith("LIMIT 1")
    assert "body_redacted" not in result.executed_sql


def test_executor_rejects_unsafe_sql_before_opening_a_connection():
    engine = create_engine("sqlite://", future=True)
    with __import__("pytest").raises(SQLSafetyError):
        ReadonlyQueryExecutor(engine).execute("SELECT body_redacted FROM tickets")
