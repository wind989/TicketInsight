"""Persistence tests keep workflow traces, evidence and SQL audits reviewable without a real database account."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import AgentTrace, AnalysisEvidence, AnalysisFeedback, AnalysisRun, Base, SQLAudit
from app.services.agent_workflow import AnalysisDraft, SQLPlan, TicketInsightWorkflow
from app.services.analysis_runs import add_feedback, run_and_persist
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import validate_readonly_select


class Planner:
    def plan(self, question, evidence, prior_error):
        return SQLPlan("SELECT category, COUNT(*) AS ticket_count FROM tickets GROUP BY category", "固定统计")


class Advisor:
    def draft(self, question, evidence, result, sql_error):
        return AnalysisDraft("支付类工单需要关注。", "固定合成数据的离线验证。")


class Reviewer:
    def review(self, question, evidence, result, draft):
        return "approved"


def test_analysis_run_persists_redacted_evidence_audit_trace_and_feedback():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    evidence = [RetrievedEvidence("ticket", 7, "支付状态延迟", "支付状态同步延迟。", "payment", 1, 0.92, "fake", 64)]

    def query(sql: str) -> QueryResult:
        validated = validate_readonly_select(sql)
        return QueryResult([{"category": "payment", "ticket_count": 4}], 1, 3, validated.sql, validated.audit_sql, validated.tables)

    workflow = TicketInsightWorkflow(
        retrieval_tool=lambda _: evidence,
        sql_planner=Planner(),
        query_tool=query,
        attribution_advisor=Advisor(),
        reviewer=Reviewer(),
    )
    with Session(engine) as session:
        persisted = run_and_persist(session, workflow, "为什么支付类投诉增加？", retriever_model="fake")
        feedback = add_feedback(session, persisted.run_id, helpful=True, reason_redacted="统计与证据可复查。")
        run = session.get(AnalysisRun, persisted.run_id)
        assert run is not None and run.status == "completed"
        assert persisted.result.run_id == persisted.run_id
        assert persisted.result.context_snapshot is not None
        assert session.scalars(select(AnalysisEvidence).where(AnalysisEvidence.run_id == persisted.run_id)).one().business_id == 7
        assert session.scalars(select(SQLAudit).where(SQLAudit.run_id == persisted.run_id)).one().audit_sql is not None
        assert len(list(session.scalars(select(AgentTrace).where(AgentTrace.run_id == persisted.run_id)))) == 5
        assert feedback.run_id == persisted.run_id
        assert session.scalars(select(AnalysisFeedback).where(AnalysisFeedback.run_id == persisted.run_id)).one().helpful is True
