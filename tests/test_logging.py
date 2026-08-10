"""Log redaction unit tests: secrets and PII never survive structured serialization."""

from __future__ import annotations

import logging

from app.core.logging import JSONFormatter, redact_value


def test_redaction_removes_sensitive_keys_ticket_text_email_and_phone():
    value = redact_value(
        {
            "Authorization": "Bearer secret",
            "question": "联系 test@example.com 或 13800138000",
            "nested": {"api_key": "key", "summary": "保留统计"},
        }
    )

    assert value["Authorization"] == "[redacted]"
    assert value["question"] == "[redacted]"
    assert value["nested"]["api_key"] == "[redacted]"
    assert value["nested"]["summary"] == "保留统计"


def test_json_formatter_outputs_only_allowlisted_metadata_fields():
    record = logging.LogRecord("ticketinsight", logging.INFO, "", 0, "request_completed", (), None)
    record.request_id = "r-1"
    record.method = "POST"
    record.path = "/api/v1/analysis-runs"
    record.status_code = 503
    record.duration_ms = 4
    record.authorization = "must not appear"
    record.question = "must not appear"

    rendered = JSONFormatter().format(record)

    assert "must not appear" not in rendered
    assert '"path":"/api/v1/analysis-runs"' in rendered
