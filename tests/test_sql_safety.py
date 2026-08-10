"""Security tests for the SQL AST gate; all cases stop before a database connection."""

from __future__ import annotations

import pytest

from app.services.sql_safety import SQLSafetyError, validate_readonly_select


def test_boolean_and_conditions_are_allowed_without_expanding_the_function_whitelist():
    validated = validate_readonly_select(
        "SELECT id, status, priority, module_id FROM tickets "
        "WHERE category = 'payment' AND priority = 'high' AND status <> 'closed' LIMIT 50"
    )

    assert validated.tables == ("tickets",)
    assert validated.max_rows == 200


def test_valid_select_is_normalized_bounded_and_auditable():
    result = validate_readonly_select(
        "SELECT t.category, COUNT(*) AS ticket_count FROM tickets AS t WHERE t.priority = 'high' GROUP BY t.category"
    )

    assert result.tables == ("tickets",)
    assert result.sql.endswith("LIMIT 200")
    assert "'high'" in result.sql
    assert "'[redacted]'" in result.audit_sql
    assert "'high'" not in result.audit_sql


def test_timestampdiff_is_limited_to_ticket_sla_duration_checks():
    result = validate_readonly_select(
        "SELECT tickets.id, tickets.status FROM tickets "
        "WHERE tickets.resolved_at IS NOT NULL "
        "AND TIMESTAMPDIFF(HOUR, tickets.created_at, tickets.resolved_at) > 24 LIMIT 20"
    )

    assert result.tables == ("tickets",)
    assert "TIMESTAMPDIFF(HOUR, tickets.created_at, tickets.resolved_at)" in result.sql


def test_timestampdiff_allows_a_fixed_controlled_timestamp_for_open_sla_age():
    result = validate_readonly_select(
        "SELECT tickets.id FROM tickets "
        "WHERE TIMESTAMPDIFF(DAY, tickets.created_at, '2026-08-01 00:00:00') > 3 LIMIT 10"
    )

    assert "TIMESTAMPDIFF(DAY, tickets.created_at, '[redacted]')" in result.audit_sql


@pytest.mark.parametrize(
    "candidate",
    [
        "SELECT tickets.id FROM tickets WHERE TIMESTAMPDIFF(SECOND, tickets.created_at, tickets.resolved_at) > 1 LIMIT 10",
        "SELECT tickets.id FROM tickets WHERE TIMESTAMPDIFF(HOUR, DATE(tickets.created_at), tickets.resolved_at) > 1 LIMIT 10",
        "SELECT tickets.id FROM tickets WHERE TIMESTAMPDIFF(HOUR, tickets.created_at, 1) > 1 LIMIT 10",
        "SELECT tickets.id FROM tickets WHERE TIMESTAMPDIFF(HOUR, tickets.created_at, tickets.body_redacted) > 1 LIMIT 10",
        "SELECT tickets.id FROM tickets JOIN ticket_events ON ticket_events.ticket_id = tickets.id "
        "WHERE TIMESTAMPDIFF(HOUR, tickets.created_at, ticket_events.occurred_at) > 1 LIMIT 10",
    ],
)
def test_timestampdiff_rejects_unapproved_units_arguments_nesting_and_cross_table_values(candidate):
    with pytest.raises(SQLSafetyError):
        validate_readonly_select(candidate)


@pytest.mark.parametrize(
    "candidate",
    [
        "DELETE FROM tickets",
        "SELECT * FROM tickets",
        "SELECT body_redacted FROM tickets",
        "SELECT SLEEP(1) FROM tickets",
        "SELECT id FROM other_schema.tickets",
        "SELECT id FROM tickets; DELETE FROM tickets",
        "SELECT id FROM tickets WHERE id IN (SELECT id FROM tickets)",
        "SELECT id FROM tickets WHERE id = 'test@example.com'",
        "SELECT id FROM tickets LIMIT 1000",
    ],
)
def test_unsafe_or_unbounded_select_is_rejected_or_clamped(candidate):
    if candidate.endswith("LIMIT 1000"):
        assert validate_readonly_select(candidate).sql.endswith("LIMIT 200")
    else:
        with pytest.raises(SQLSafetyError):
            validate_readonly_select(candidate)
