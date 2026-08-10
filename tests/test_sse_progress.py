"""SSE progress tests: status signals only, bounded, and independent of report persistence."""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import select

from app.api.routes import _analysis_progress_stream
from app.core import database
from app.models import AnalysisRun
from app.services.agent_workflow import AnalysisDraft, SQLPlan, TicketInsightWorkflow
from app.services.analysis_runs import create_pending_run, execute_pending_run_with_progress
from app.services.progress import MAX_EVENTS_PER_RUN, progress_events
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import validate_readonly_select


class FirstUnsafeThenSafePlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, question, evidence, prior_error):
        self.calls += 1
        if self.calls == 1:
            return SQLPlan("SELECT * FROM tickets", "test unsafe candidate")
        return SQLPlan("SELECT category, COUNT(*) AS ticket_count FROM tickets GROUP BY category", "test bounded repair")


class FixedAdvisor:
    def draft(self, question, evidence, result, sql_error):
        return AnalysisDraft("Reviewed test conclusion.", "Synthetic test only.")


class ApprovingReviewer:
    def review(self, question, evidence, result, draft):
        return "approved"


def _workflow() -> TicketInsightWorkflow:
    evidence = [RetrievedEvidence("ticket", 8, "payment delay", "redacted payment delay", "payment", 1, 0.9, "fake", 64)]

    def query(sql: str) -> QueryResult:
        validated = validate_readonly_select(sql)
        return QueryResult([{"category": "payment", "ticket_count": 4}], 1, 1, validated.sql, validated.audit_sql, validated.tables)

    return TicketInsightWorkflow(
        retrieval_tool=lambda _: evidence,
        sql_planner=FirstUnsafeThenSafePlanner(),
        query_tool=query,
        attribution_advisor=FixedAdvisor(),
        reviewer=ApprovingReviewer(),
    )


def test_fake_llm_workflow_emits_safe_order_and_repairs_rejected_sql_once():
    workflow = _workflow()
    events: list[tuple[str, str, str]] = []

    result = workflow.run("Why did payment tickets increase?", progress_reporter=lambda *event: events.append(event))

    assert result.status == "completed"
    assert [stage for stage, _, _ in events] == [
        "retrieval_started",
        "retrieval_completed",
        "sql_validation_rejected",
        "sql_repair_started",
        "query_completed",
        "draft_completed",
        "review_completed",
    ]
    rendered = json.dumps(events)
    assert "SELECT" not in rendered
    assert "payment tickets increase" not in rendered
    assert "redacted payment delay" not in rendered


def test_persisted_run_emits_terminal_event_after_sql_repair(client):
    progress_events.reset()
    with database.SessionLocal() as session:
        run = create_pending_run(session, "Why did payment tickets increase?", retriever_model="fake")

    execute_pending_run_with_progress(run.id, _workflow())

    with database.SessionLocal() as session:
        saved = session.get(AnalysisRun, run.id)
        assert saved is not None and saved.status == "completed"
        assert session.scalars(select(AnalysisRun).where(AnalysisRun.id == run.id)).one().completed_at is not None
    events = progress_events.after(run.id, 0)
    assert [event.stage for event in events][-1] == "analysis_completed"
    assert events[-1].status == "completed"


def test_failed_background_run_persists_failure_and_never_exposes_exception_text(client):
    class FailingWorkflow:
        def run(self, question, *, progress_reporter=None):
            if progress_reporter:
                progress_reporter("retrieval_started", "started", "Approved evidence retrieval started.")
            raise RuntimeError("mysql://root:secret@host/hidden")

    progress_events.reset()
    with database.SessionLocal() as session:
        run = create_pending_run(session, "Why did payment tickets increase?", retriever_model="fake")

    execute_pending_run_with_progress(run.id, FailingWorkflow())

    with database.SessionLocal() as session:
        saved = session.get(AnalysisRun, run.id)
        assert saved is not None and saved.status == "failed" and saved.completed_at is not None
    rendered = json.dumps([event.payload() for event in progress_events.after(run.id, 0)])
    assert "secret" not in rendered
    assert "mysql" not in rendered
    assert progress_events.after(run.id, 0)[-1].stage == "failed"


def test_sse_endpoint_returns_only_status_contract_and_not_found_for_unknown_run(client):
    progress_events.reset()
    with database.SessionLocal() as session:
        run = AnalysisRun(question_redacted="safe question", status="completed", graph_version="fixed-langgraph-v1")
        session.add(run)
        session.commit()
        session.refresh(run)
    progress_events.emit(run.id, "analysis_completed", "completed", "Analysis completed with bounded safeguards.")

    response = client.get(f"/api/v1/analysis-runs/{run.id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    data_line = next(line for line in response.text.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert set(payload) == {"run_id", "stage", "status", "summary", "timestamp"}
    assert payload["run_id"] == run.id
    assert "safe question" not in response.text
    assert "SELECT" not in response.text
    assert client.get("/api/v1/analysis-runs/not-a-real-run/events").status_code == 404


def test_client_disconnect_stops_only_stream_not_the_running_analysis_record(client):
    class DisconnectingRequest:
        async def is_disconnected(self) -> bool:
            return False

    progress_events.reset()
    with database.SessionLocal() as session:
        run = AnalysisRun(question_redacted="safe question", status="running", graph_version="fixed-langgraph-v1")
        session.add(run)
        session.commit()
        session.refresh(run)
    progress_events.emit(run.id, "retrieval_started", "started", "Approved evidence retrieval started.")

    async def consume_then_cancel() -> str:
        stream = _analysis_progress_stream(run.id, DisconnectingRequest())
        first = await anext(stream)
        await stream.aclose()
        return first

    first_frame = asyncio.run(consume_then_cancel())

    assert "retrieval_started" in first_frame
    with database.SessionLocal() as session:
        assert session.get(AnalysisRun, run.id).status == "running"


def test_progress_store_is_bounded_and_accepts_only_prebuilt_safe_summaries():
    progress_events.reset()
    run_id = "bounded-progress-run"
    for _ in range(MAX_EVENTS_PER_RUN + 5):
        progress_events.emit(run_id, "retrieval_started", "started", "Approved evidence retrieval started.")
    events = progress_events.after(run_id, 0)
    assert len(events) == MAX_EVENTS_PER_RUN
    assert events[0].sequence == 6
    with pytest.raises(ValueError):
        progress_events.emit(run_id, "analysis_completed", "completed", "Raw model conclusion: secret")
