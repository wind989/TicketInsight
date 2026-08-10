"""LangGraph tests prove the fixed node path and one-revision ceilings without a real LLM or database account."""

from __future__ import annotations

from app.services.agent_workflow import AnalysisDraft, SQLPlan, TicketInsightWorkflow
from app.services.llm_advisor import OpenAICompatibleAdvisor
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import SQLSafetyError, validate_readonly_select


def _evidence(_: str) -> list[RetrievedEvidence]:
    return [RetrievedEvidence("ticket", 8, "支付延迟", "支付回调延迟。", "payment", 1, 0.9, "fake", 64)]


def _query(sql: str) -> QueryResult:
    validated = validate_readonly_select(sql)
    return QueryResult([{"category": "payment", "ticket_count": 4}], 1, 1, validated.sql, validated.audit_sql, validated.tables)


class FirstUnsafeThenSafePlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, question, evidence, prior_error):
        self.calls += 1
        if self.calls == 1:
            return SQLPlan("SELECT * FROM tickets", "故意触发安全闸门测试")
        return SQLPlan("SELECT category, COUNT(*) AS ticket_count FROM tickets GROUP BY category", "单次修订后的安全统计")


class FixedAdvisor:
    def draft(self, question, evidence, result, sql_error):
        return AnalysisDraft("存在支付类工单统计结果。", "基于固定合成数据和受控统计。")


class ApprovingReviewer:
    def review(self, question, evidence, result, draft):
        return "approved"


class AlwaysConclusionRevisionReviewer:
    def review(self, question, evidence, result, draft):
        return "revise_conclusion"


class AlwaysFailingPlanner:
    def __init__(self) -> None:
        self.calls = 0

    def plan(self, question, evidence, prior_error):
        self.calls += 1
        raise RuntimeError("planner unavailable")


class SafePlanner:
    def plan(self, question, evidence, prior_error):
        return SQLPlan("SELECT id FROM tickets ORDER BY id LIMIT 1", "bounded test query")


class AlwaysFailingAdvisor:
    def draft(self, question, evidence, result, sql_error):
        raise RuntimeError("advisor unavailable")


def test_graph_repairs_sql_once_after_deterministic_gate_rejection():
    planner = FirstUnsafeThenSafePlanner()
    workflow = TicketInsightWorkflow(
        retrieval_tool=_evidence,
        sql_planner=planner,
        query_tool=_query,
        attribution_advisor=FixedAdvisor(),
        reviewer=ApprovingReviewer(),
    )

    result = workflow.run("支付投诉为什么增加？")

    assert result.status == "completed"
    assert result.sql_revisions == 1
    assert planner.calls == 2
    assert [event["node"] for event in result.trace].count("plan_sql") == 2
    assert [event["node"] for event in result.trace].count("execute_safe_sql") == 2


def test_graph_stops_after_one_conclusion_revision_even_if_reviewer_repeats_request():
    workflow = TicketInsightWorkflow(
        retrieval_tool=_evidence,
        sql_planner=FirstUnsafeThenSafePlanner(),
        query_tool=_query,
        attribution_advisor=FixedAdvisor(),
        reviewer=AlwaysConclusionRevisionReviewer(),
    )

    result = workflow.run("支付投诉为什么增加？")

    assert result.conclusion_revisions == 1
    assert "已达到单次修订上限" in result.limitations
    assert [event["node"] for event in result.trace].count("draft_analysis") == 2


def test_graph_stops_after_one_failed_sql_planning_repair_instead_of_recursing():
    planner = AlwaysFailingPlanner()
    workflow = TicketInsightWorkflow(
        retrieval_tool=_evidence,
        sql_planner=planner,
        query_tool=_query,
        attribution_advisor=FixedAdvisor(),
        reviewer=ApprovingReviewer(),
    )

    result = workflow.run("payment operations question")

    assert result.status == "limited"
    assert result.sql_revisions == 1
    assert planner.calls == 2
    assert [event["node"] for event in result.trace].count("plan_sql") == 2
    assert [event["node"] for event in result.trace].count("execute_safe_sql") == 2


def test_graph_stops_after_one_failed_conclusion_repair_instead_of_recursing():
    workflow = TicketInsightWorkflow(
        retrieval_tool=_evidence,
        sql_planner=SafePlanner(),
        query_tool=_query,
        attribution_advisor=AlwaysFailingAdvisor(),
        reviewer=AlwaysConclusionRevisionReviewer(),
    )

    result = workflow.run("payment operations question")

    assert result.status == "completed"
    assert result.conclusion_revisions == 1
    assert [event["node"] for event in result.trace].count("draft_analysis") == 2


def test_real_advisor_sql_prompt_contains_the_non_negotiable_ast_contract():
    advisor = object.__new__(OpenAICompatibleAdvisor)
    captured: dict[str, object] = {}

    def fake_complete(instruction: str, payload: dict[str, object]) -> dict[str, str]:
        captured["instruction"] = instruction
        captured["payload"] = payload
        return {"sql": "SELECT id FROM tickets LIMIT 1", "rationale": "bounded ticket sample"}

    advisor._complete = fake_complete  # type: ignore[method-assign]
    plan = advisor.plan("支付问题", [], "只允许单条 SELECT")

    assert plan.sql == "SELECT id FROM tickets LIMIT 1"
    instruction = str(captured["instruction"])
    assert "Never use a semicolon" in instruction
    assert "CTE/WITH" in instruction
    assert "SELECT id, status, priority, module_id FROM tickets" in instruction
