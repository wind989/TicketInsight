"""Create persistent analysis, evidence, SQL-audit, trace, and feedback records.

Revision ID: 20260809_0002
Revises: 20260809_0001
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0002"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("question_redacted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("graph_version", sa.String(length=80), nullable=False),
        sa.Column("retriever_model", sa.String(length=160), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "analysis_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("excerpt_redacted", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
    )
    op.create_index("ix_analysis_evidence_run_id", "analysis_evidence", ["run_id"])
    op.create_table(
        "sql_audits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("audit_sql", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sql_audits_run_id", "sql_audits", ["run_id"])
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("node", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_traces_run_id", "agent_traces", ["run_id"])
    op.create_table(
        "analysis_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("analysis_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("reason_redacted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_feedback_run_id", "analysis_feedback", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_feedback_run_id", table_name="analysis_feedback")
    op.drop_table("analysis_feedback")
    op.drop_index("ix_agent_traces_run_id", table_name="agent_traces")
    op.drop_table("agent_traces")
    op.drop_index("ix_sql_audits_run_id", table_name="sql_audits")
    op.drop_table("sql_audits")
    op.drop_index("ix_analysis_evidence_run_id", table_name="analysis_evidence")
    op.drop_table("analysis_evidence")
    op.drop_table("analysis_runs")
