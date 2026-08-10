"""Create TicketInsight P0 domain tables.

Revision ID: 20260809_0001
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("anonymous_id", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("anonymous_id", name="uq_customers_anonymous_id"),
    )
    op.create_index("ix_customers_anonymous_id", "customers", ["anonymous_id"])
    op.create_table(
        "product_modules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_product_modules_name"),
    )
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("response_minutes", sa.Integer(), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("category", "priority", name="uq_sla_policy_category_priority"),
    )
    op.create_index("ix_sla_policies_category", "sla_policies", ["category"])
    op.create_index("ix_sla_policies_priority", "sla_policies", ["priority"])
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_redacted", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("module_id", sa.Integer(), sa.ForeignKey("product_modules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("category", "priority", "status", "customer_id", "module_id", "created_at"):
        op.create_index(f"ix_tickets_{column}", "tickets", [column])
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_group", sa.String(length=40), nullable=False),
        sa.Column("note_redacted", sa.Text(), nullable=True),
    )
    for column in ("ticket_id", "event_type", "occurred_at"):
        op.create_index(f"ix_ticket_events_{column}", "ticket_events", [column])
    op.create_table(
        "service_knowledge",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_redacted", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("module_id", sa.Integer(), sa.ForeignKey("product_modules.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("source_type", "category", "module_id"):
        op.create_index(f"ix_service_knowledge_{column}", "service_knowledge", [column])


def downgrade() -> None:
    for column in ("source_type", "category", "module_id"):
        op.drop_index(f"ix_service_knowledge_{column}", table_name="service_knowledge")
    op.drop_table("service_knowledge")
    for column in ("ticket_id", "event_type", "occurred_at"):
        op.drop_index(f"ix_ticket_events_{column}", table_name="ticket_events")
    op.drop_table("ticket_events")
    for column in ("category", "priority", "status", "customer_id", "module_id", "created_at"):
        op.drop_index(f"ix_tickets_{column}", table_name="tickets")
    op.drop_table("tickets")
    op.drop_index("ix_sla_policies_priority", table_name="sla_policies")
    op.drop_index("ix_sla_policies_category", table_name="sla_policies")
    op.drop_table("sla_policies")
    op.drop_table("product_modules")
    op.drop_index("ix_customers_anonymous_id", table_name="customers")
    op.drop_table("customers")
