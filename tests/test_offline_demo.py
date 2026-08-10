"""The offline demo verifies the closed graph while making its fake dependencies explicit."""

from __future__ import annotations

from app.services.offline_demo import run_offline_demo


def test_offline_demo_produces_evidence_sql_audit_and_limited_report():
    report = run_offline_demo()

    assert report["mode"] == "offline_fake"
    assert report["status"] == "completed"
    assert report["evidence"]
    assert report["sql_audits"][0]["status"] == "executed"
    assert report["query_rows"] == [{"category": "payment", "ticket_count": 4}]
    assert "不代表真实 MySQL" in report["limitations"]
