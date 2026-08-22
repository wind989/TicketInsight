"""Agent evaluation reports graph mechanics, not fabricated answer accuracy."""

from __future__ import annotations

from app.services.agent_context import ContextSnapshot
from app.services.agent_workflow import AnalysisDraft, SQLPlan, TicketInsightWorkflow
from app.services.evaluation import score_agent_observables, summarize_agent_observables
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import validate_readonly_select
from scripts.evaluate_agent_observables import evaluate


class Planner:
    def plan(self, question, evidence, prior_error):
        return SQLPlan("SELECT id FROM tickets ORDER BY id LIMIT 1", "bounded")


class Advisor:
    def draft(self, question, evidence, result, sql_error):
        return AnalysisDraft("统计完成。", "仅适用于合成数据。")


class Reviewer:
    def review(self, question, evidence, result, draft):
        return "approved"


def test_agent_observables_measure_roles_context_and_revision_limits():
    evidence = [RetrievedEvidence("ticket", 1, "标题", "脱敏内容", "payment", 1, 0.9, "fake", 64)]

    def query(sql: str) -> QueryResult:
        validated = validate_readonly_select(sql)
        return QueryResult([{"id": 1}], 1, 1, validated.sql, validated.audit_sql, validated.tables)

    workflow = TicketInsightWorkflow(
        retrieval_tool=lambda _: evidence,
        sql_planner=Planner(),
        query_tool=query,
        attribution_advisor=Advisor(),
        reviewer=Reviewer(),
    )
    result = workflow.run("支付问题", run_id="observable-1")
    facts = score_agent_observables(result)

    assert facts["fixed_role_path_observed"] is True
    assert facts["review_observed"] is True
    assert facts["revision_bounds_safe"] is True
    assert facts["status_query_consistent"] is True
    assert facts["context_bounds_safe"] is True
    assert facts["checkpoint_run_id_present"] is True
    summary = summarize_agent_observables([facts])
    assert summary["fixed_role_path_rate"] == 1.0
    assert summary["semantic_conclusion_scoring"] == "not_automated"


def test_observable_scoring_refuses_to_claim_context_without_snapshot():
    result = type("Result", (), {
        "status": "limited",
        "trace": [{"node": "review"}],
        "sql_revisions": 0,
        "conclusion_revisions": 0,
        "query_result": None,
        "context_snapshot": None,
        "run_id": "limited-1",
    })()
    facts = score_agent_observables(result)
    assert facts["context_bounds_safe"] is False


def test_offline_observable_evaluation_covers_the_fixed_question_set():
    report = evaluate()
    assert report["mode"] == "offline_fake_agent_mechanics"
    assert report["report"]["total_runs"] == 15
    assert report["report"]["fixed_role_path_rate"] == 1.0
