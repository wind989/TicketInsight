"""Persist only redacted, reviewable facts from a completed fixed workflow run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import database
from app.models import AgentTrace, AnalysisEvidence, AnalysisFeedback, AnalysisRun, SQLAudit
from app.schemas import reject_pii_text
from app.services.agent_workflow import TicketInsightWorkflow, WorkflowResult
from app.services.progress import progress_events


GRAPH_VERSION = "fixed-langgraph-v2-agent-contracts"


@dataclass(frozen=True)
class PersistedAnalysis:
    run_id: str
    result: WorkflowResult


def create_pending_run(session: Session, question: str, *, retriever_model: str | None) -> AnalysisRun:
    """Commit an auditable running record before the independent background task begins."""

    safe_question = reject_pii_text(question)
    if safe_question is None:
        raise ValueError("Question cannot be empty")
    run = AnalysisRun(
        question_redacted=safe_question,
        status="running",
        graph_version=GRAPH_VERSION,
        retriever_model=retriever_model,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _save_completed_result(session: Session, run: AnalysisRun, result: WorkflowResult, started_at: float) -> PersistedAnalysis:
    """Save the same reviewed report material used by the synchronous API."""

    run.status = result.status
    run.total_duration_ms = round((perf_counter() - started_at) * 1000)
    run.conclusion = result.conclusion
    run.limitations = result.limitations
    run.completed_at = datetime.now(timezone.utc)
    session.add_all(
        [
            AnalysisEvidence(
                run_id=run.id,
                source_type=evidence.source_type,
                business_id=evidence.source_id,
                title=evidence.title,
                excerpt_redacted=evidence.excerpt_redacted,
                score=evidence.score,
            )
            for evidence in result.evidence
        ]
    )
    session.add_all(
        [
            SQLAudit(
                run_id=run.id,
                attempt_index=index,
                status=audit["status"],
                audit_sql=audit["audit_sql"],
                rejection_reason=audit["rejection_reason"],
                duration_ms=audit["duration_ms"],
                row_count=audit["row_count"],
            )
            for index, audit in enumerate(result.sql_audits, start=1)
        ]
    )
    session.add_all(
        [AgentTrace(run_id=run.id, node=trace["node"], status=trace["status"], duration_ms=trace["duration_ms"]) for trace in result.trace]
    )
    session.commit()
    return PersistedAnalysis(run_id=run.id, result=result)


def execute_pending_run(run_id: str, workflow: TicketInsightWorkflow) -> PersistedAnalysis:
    """Execute a committed run with a fresh session, independent of the SSE request."""

    session = database.SessionLocal()
    started_at = perf_counter()
    try:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise LookupError("Analysis run no longer exists")
        if run.status != "running":
            raise RuntimeError("Analysis run is not pending")
        try:
            result = workflow.run(
                run.question_redacted,
                run_id=run.id,
                progress_reporter=lambda stage, event_status, summary: progress_events.emit(
                    run_id, stage, event_status, summary
                ),
            )
        except Exception as error:
            run.status = "failed"
            run.total_duration_ms = round((perf_counter() - started_at) * 1000)
            run.limitations = f"Fixed workflow failed safely: {type(error).__name__}"
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise
        return _save_completed_result(session, run, result, started_at)
    finally:
        session.close()


def execute_pending_run_with_progress(run_id: str, workflow: TicketInsightWorkflow) -> None:
    """Publish only terminal, constant summaries after the independent workflow task ends."""

    try:
        persisted = execute_pending_run(run_id, workflow)
    except Exception:
        progress_events.emit(run_id, "failed", "failed", "Analysis failed safely; final status is available from the report API.")
        return
    if persisted.result.status == "completed":
        progress_events.emit(run_id, "analysis_completed", "completed", "Analysis completed with bounded safeguards.")
    else:
        progress_events.emit(run_id, "analysis_completed", "limited", "Analysis completed with documented limitations.")


def run_and_persist(
    session: Session,
    workflow: TicketInsightWorkflow,
    question: str,
    *,
    retriever_model: str | None,
) -> PersistedAnalysis:
    """Execute one bounded workflow and save evidence/audits/traces without raw credentials or PII."""

    safe_question = reject_pii_text(question)
    if safe_question is None:
        raise ValueError("问题不能为空")
    started_at = perf_counter()
    run = AnalysisRun(question_redacted=safe_question, status="running", graph_version=GRAPH_VERSION, retriever_model=retriever_model)
    session.add(run)
    session.flush()
    try:
        result = workflow.run(safe_question, run_id=run.id)
    except Exception as error:
        run.status = "failed"
        run.total_duration_ms = round((perf_counter() - started_at) * 1000)
        run.limitations = f"固定工作流异常：{type(error).__name__}"
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise

    run.status = result.status
    run.total_duration_ms = round((perf_counter() - started_at) * 1000)
    run.conclusion = result.conclusion
    run.limitations = result.limitations
    run.completed_at = datetime.now(timezone.utc)
    session.add_all(
        [
            AnalysisEvidence(
                run_id=run.id,
                source_type=evidence.source_type,
                business_id=evidence.source_id,
                title=evidence.title,
                excerpt_redacted=evidence.excerpt_redacted,
                score=evidence.score,
            )
            for evidence in result.evidence
        ]
    )
    session.add_all(
        [
            SQLAudit(
                run_id=run.id,
                attempt_index=index,
                status=audit["status"],
                audit_sql=audit["audit_sql"],
                rejection_reason=audit["rejection_reason"],
                duration_ms=audit["duration_ms"],
                row_count=audit["row_count"],
            )
            for index, audit in enumerate(result.sql_audits, start=1)
        ]
    )
    session.add_all(
        [AgentTrace(run_id=run.id, node=trace["node"], status=trace["status"], duration_ms=trace["duration_ms"]) for trace in result.trace]
    )
    session.commit()
    return PersistedAnalysis(run_id=run.id, result=result)


def add_feedback(session: Session, run_id: str, helpful: bool, reason_redacted: str | None = None) -> AnalysisFeedback:
    """Store explicit human feedback only for an existing analysis run, with the same PII boundary as requests."""

    if session.scalar(select(AnalysisRun.id).where(AnalysisRun.id == run_id)) is None:
        raise LookupError("分析运行不存在")
    feedback = AnalysisFeedback(run_id=run_id, helpful=helpful, reason_redacted=reject_pii_text(reason_redacted))
    session.add(feedback)
    session.commit()
    session.refresh(feedback)
    return feedback
