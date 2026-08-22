"""Fixed LangGraph workflow for evidence-backed operations analysis, with bounded revisions and no free tool loop."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from threading import RLock
from time import perf_counter
from typing import Annotated, Any, Callable, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services.agent_context import BoundedMemorySaver, ContextSnapshot, snapshot_from_state
from app.services.agent_workflow_types import AnalysisDraft, ReviewDecision, SQLPlan
from app.services.readonly_query import QueryResult, ReadonlyQueryExecutionError
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import SQLSafetyError, validate_readonly_select


RetrievalTool = Callable[[str], list[RetrievedEvidence]]
QueryTool = Callable[[str], QueryResult]
ProgressReporter = Callable[[str, str, str], None]


class SQLPlanner(Protocol):
    def plan(self, question: str, evidence: list[RetrievedEvidence], prior_error: str | None) -> SQLPlan: ...


class AttributionAdvisor(Protocol):
    def draft(self, question: str, evidence: list[RetrievedEvidence], result: QueryResult | None, sql_error: str | None) -> AnalysisDraft: ...


class Reviewer(Protocol):
    def review(self, question: str, evidence: list[RetrievedEvidence], result: QueryResult | None, draft: AnalysisDraft) -> ReviewDecision: ...


class TraceEvent(TypedDict):
    node: str
    duration_ms: int
    status: str


class SQLAuditEvent(TypedDict):
    status: str
    audit_sql: str | None
    rejection_reason: str | None
    duration_ms: int | None
    row_count: int | None


class AnalysisState(TypedDict, total=False):
    run_id: str
    question: str
    evidence: list[RetrievedEvidence]
    sql_candidate: str
    sql_rationale: str
    sql_error: str | None
    query_result: QueryResult | None
    draft: AnalysisDraft
    review_decision: ReviewDecision
    sql_plan_attempts: int
    sql_revisions: int
    draft_attempts: int
    conclusion_revisions: int
    trace: Annotated[list[TraceEvent], operator.add]
    sql_audits: Annotated[list[SQLAuditEvent], operator.add]
    final_status: str


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    evidence: list[RetrievedEvidence]
    sql_candidate: str | None
    query_result: QueryResult | None
    conclusion: str
    limitations: str
    trace: list[TraceEvent]
    sql_audits: list[SQLAuditEvent]
    sql_revisions: int
    conclusion_revisions: int
    run_id: str = ""
    context_snapshot: ContextSnapshot | None = None


def _event(node: str, started_at: float, status: str) -> list[TraceEvent]:
    return [{"node": node, "duration_ms": round((perf_counter() - started_at) * 1000), "status": status}]


class TicketInsightWorkflow:
    """Compile a closed graph with bounded role revisions and per-run checkpoints."""

    def __init__(
        self,
        *,
        retrieval_tool: RetrievalTool,
        sql_planner: SQLPlanner,
        query_tool: QueryTool,
        attribution_advisor: AttributionAdvisor,
        reviewer: Reviewer,
    ) -> None:
        self.retrieval_tool = retrieval_tool
        self.sql_planner = sql_planner
        self.query_tool = query_tool
        self.attribution_advisor = attribution_advisor
        self.reviewer = reviewer
        self.checkpointer = BoundedMemorySaver(max_threads=64)
        self._reporters: dict[str, ProgressReporter] = {}
        self._reporter_lock = RLock()
        self.graph = self._build_graph()

    def _progress(self, state: AnalysisState, stage: str, status: str, summary: str) -> None:
        """Report a constant, non-content signal kept outside serializable graph state."""

        run_id = state.get("run_id")
        if not run_id:
            return
        with self._reporter_lock:
            reporter = self._reporters.get(run_id)
        if reporter is None:
            return
        try:
            reporter(stage, status, summary)
        except Exception:
            # Progress is observational only. Do not retain exception detail because
            # it could contain runtime configuration or model-provider information.
            return

    def context_snapshot(self, run_id: str) -> ContextSnapshot | None:
        """Return only aggregate state for a run; raw checkpoint values stay internal."""

        config = {"configurable": {"thread_id": run_id}}
        try:
            checkpoint = self.graph.get_state(config)
        except Exception:
            return None
        if not checkpoint or not checkpoint.values:
            return None
        return snapshot_from_state(run_id, checkpoint.values)

    def _build_graph(self):
        workflow = StateGraph(AnalysisState)
        workflow.add_node("retrieve_evidence", self._retrieve_evidence)
        workflow.add_node("plan_sql", self._plan_sql)
        workflow.add_node("execute_safe_sql", self._execute_safe_sql)
        workflow.add_node("draft_analysis", self._draft_analysis)
        workflow.add_node("review", self._review)
        workflow.add_edge(START, "retrieve_evidence")
        workflow.add_edge("retrieve_evidence", "plan_sql")
        workflow.add_edge("plan_sql", "execute_safe_sql")
        workflow.add_conditional_edges("execute_safe_sql", self._after_sql, {"plan_sql": "plan_sql", "draft_analysis": "draft_analysis"})
        workflow.add_edge("draft_analysis", "review")
        workflow.add_conditional_edges("review", self._after_review, {"plan_sql": "plan_sql", "draft_analysis": "draft_analysis", "end": END})
        return workflow.compile(checkpointer=self.checkpointer)

    def _retrieve_evidence(self, state: AnalysisState) -> dict[str, Any]:
        started_at = perf_counter()
        try:
            evidence = self.retrieval_tool(state["question"])
            self._progress(state, "retrieval_completed", "completed", "Approved evidence retrieval completed.")
            return {"evidence": evidence, "trace": _event("retrieve_evidence", started_at, "passed")}
        except Exception as error:
            self._progress(state, "retrieval_completed", "failed", "Evidence retrieval was unavailable; safeguards remain active.")
            return {"evidence": [], "sql_error": f"检索不可用：{type(error).__name__}", "trace": _event("retrieve_evidence", started_at, "failed")}

    def _plan_sql(self, state: AnalysisState) -> dict[str, Any]:
        started_at = perf_counter()
        plan_attempts = state.get("sql_plan_attempts", 0) + 1
        revisions = max(0, plan_attempts - 1)
        if plan_attempts > 1:
            self._progress(state, "sql_repair_started", "started", "One bounded SQL repair is starting.")
        try:
            plan = self.sql_planner.plan(state["question"], state.get("evidence", []), state.get("sql_error"))
            return {
                "sql_candidate": plan.sql,
                "sql_rationale": plan.rationale,
                "sql_error": None,
                "sql_plan_attempts": plan_attempts,
                "sql_revisions": revisions,
                "trace": _event("plan_sql", started_at, "passed"),
            }
        except Exception as error:
            return {
                "sql_candidate": "",
                "sql_error": f"SQL planning unavailable: {type(error).__name__}",
                "sql_plan_attempts": plan_attempts,
                "sql_revisions": revisions,
                "trace": _event("plan_sql", started_at, "failed"),
            }

    def _execute_safe_sql(self, state: AnalysisState) -> dict[str, Any]:
        started_at = perf_counter()
        candidate = state.get("sql_candidate")
        if not candidate:
            self._progress(state, "sql_validation_rejected", "rejected", "Candidate SQL was blocked before execution.")
            message = state.get("sql_error") or "未生成 SQL"
            return {"sql_error": message, "trace": _event("execute_safe_sql", started_at, "blocked"), "sql_audits": [{"status": "rejected", "audit_sql": None, "rejection_reason": message, "duration_ms": None, "row_count": None}]}
        try:
            validated = validate_readonly_select(candidate)
        except SQLSafetyError as error:
            self._progress(state, "sql_validation_rejected", "rejected", "Candidate SQL was blocked before execution.")
            message = str(error)
            return {"query_result": None, "sql_error": message, "trace": _event("execute_safe_sql", started_at, "blocked"), "sql_audits": [{"status": "rejected", "audit_sql": None, "rejection_reason": message, "duration_ms": None, "row_count": None}]}
        try:
            result = self.query_tool(candidate)
            self._progress(state, "query_completed", "completed", "Bounded read-only query completed.")
            return {"query_result": result, "sql_error": None, "trace": _event("execute_safe_sql", started_at, "passed"), "sql_audits": [{"status": "executed", "audit_sql": result.audit_sql, "rejection_reason": None, "duration_ms": result.duration_ms, "row_count": result.row_count}]}
        except (SQLSafetyError, ReadonlyQueryExecutionError) as error:
            self._progress(state, "query_completed", "failed", "Bounded read-only query was unavailable.")
            message = str(error)
            return {"query_result": None, "sql_error": message, "trace": _event("execute_safe_sql", started_at, "blocked"), "sql_audits": [{"status": "failed", "audit_sql": validated.audit_sql, "rejection_reason": message, "duration_ms": None, "row_count": None}]}
        except Exception as error:
            self._progress(state, "query_completed", "failed", "Bounded read-only query was unavailable.")
            message = f"只读查询不可用：{type(error).__name__}"
            return {"query_result": None, "sql_error": message, "trace": _event("execute_safe_sql", started_at, "failed"), "sql_audits": [{"status": "failed", "audit_sql": validated.audit_sql, "rejection_reason": message, "duration_ms": None, "row_count": None}]}

    @staticmethod
    def _after_sql(state: AnalysisState) -> str:
        if state.get("sql_error") and state.get("sql_revisions", 0) < 1:
            return "plan_sql"
        return "draft_analysis"

    def _draft_analysis(self, state: AnalysisState) -> dict[str, Any]:
        started_at = perf_counter()
        draft_attempts = state.get("draft_attempts", 0) + 1
        revisions = max(0, draft_attempts - 1)
        try:
            draft = self.attribution_advisor.draft(
                state["question"], state.get("evidence", []), state.get("query_result"), state.get("sql_error")
            )
            self._progress(state, "draft_completed", "completed", "Analysis draft completed from bounded inputs.")
            return {
                "draft": draft,
                "draft_attempts": draft_attempts,
                "conclusion_revisions": revisions,
                "trace": _event("draft_analysis", started_at, "passed"),
            }
        except Exception as error:
            self._progress(state, "draft_completed", "failed", "Analysis draft was unavailable; safeguards remain active.")
            return {
                "draft": AnalysisDraft("无法生成结论。", f"归因节点失败：{type(error).__name__}"),
                "draft_attempts": draft_attempts,
                "conclusion_revisions": revisions,
                "trace": _event("draft_analysis", started_at, "failed"),
            }

    def _review(self, state: AnalysisState) -> dict[str, Any]:
        started_at = perf_counter()
        draft = state.get("draft", AnalysisDraft("无法生成结论。", "缺少归因草稿。"))
        try:
            decision = self.reviewer.review(state["question"], state.get("evidence", []), state.get("query_result"), draft)
            if decision not in {"approved", "revise_sql", "revise_conclusion"}:
                decision = "approved"
            self._progress(state, "review_completed", "completed", "Bounded review completed.")
            return {"review_decision": decision, "trace": _event("review", started_at, decision)}
        except Exception as error:
            self._progress(state, "review_completed", "failed", "Review was unavailable; bounded fallback completed.")
            return {"review_decision": "approved", "trace": _event("review", started_at, f"fallback:{type(error).__name__}")}

    @staticmethod
    def _after_review(state: AnalysisState) -> str:
        decision = state.get("review_decision", "approved")
        if decision == "revise_sql" and state.get("sql_revisions", 0) < 1:
            return "plan_sql"
        if decision == "revise_conclusion" and state.get("conclusion_revisions", 0) < 1:
            return "draft_analysis"
        return "end"

    def run(
        self,
        question: str,
        *,
        run_id: str | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> WorkflowResult:
        """Run the closed graph once with a bounded, process-local checkpoint thread."""

        import uuid

        active_run_id = run_id or str(uuid.uuid4())
        if progress_reporter is not None:
            with self._reporter_lock:
                self._reporters[active_run_id] = progress_reporter
            try:
                progress_reporter("retrieval_started", "started", "Approved evidence retrieval started.")
            except Exception:
                pass
        config = {"configurable": {"thread_id": active_run_id}}
        try:
            final_state = self.graph.invoke(
                {
                    "run_id": active_run_id,
                    "question": question,
                    "sql_plan_attempts": 0,
                    "sql_revisions": 0,
                    "draft_attempts": 0,
                    "conclusion_revisions": 0,
                    "trace": [],
                    "sql_audits": [],
                },
                config,
            )
        finally:
            if progress_reporter is not None:
                with self._reporter_lock:
                    self._reporters.pop(active_run_id, None)
        draft = final_state.get("draft", AnalysisDraft("无法生成结论。", "流程未产出草稿。"))
        limitations = draft.limitations
        if final_state.get("review_decision") in {"revise_sql", "revise_conclusion"}:
            limitations = f"{limitations} 复核需要额外修订，但已达到单次修订上限。".strip()
        status = "completed" if final_state.get("query_result") is not None else "limited"
        context_snapshot = snapshot_from_state(active_run_id, final_state)
        return WorkflowResult(
            run_id=active_run_id,
            status=status,
            evidence=final_state.get("evidence", []),
            sql_candidate=final_state.get("sql_candidate"),
            query_result=final_state.get("query_result"),
            conclusion=draft.conclusion,
            limitations=limitations,
            trace=final_state.get("trace", []),
            sql_audits=final_state.get("sql_audits", []),
            sql_revisions=final_state.get("sql_revisions", 0),
            conclusion_revisions=final_state.get("conclusion_revisions", 0),
            context_snapshot=context_snapshot,
        )
