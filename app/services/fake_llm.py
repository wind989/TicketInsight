"""Offline adapters for deterministic graph tests and demos; they are not a production LLM integration."""

from __future__ import annotations

from app.services.agent_workflow import AnalysisDraft, ReviewDecision, SQLPlan
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence


class FakeOperationsLLM:
    """Produce bounded, auditable sample plans and cautious summaries without a network call or API key."""

    def plan(self, question: str, evidence: list[RetrievedEvidence], prior_error: str | None) -> SQLPlan:
        if "支付" in question:
            return SQLPlan(
                "SELECT category, COUNT(*) AS ticket_count FROM tickets WHERE category = 'payment' GROUP BY category",
                "按支付类别统计工单数量。",
            )
        if "高优先级" in question or "SLA" in question.upper():
            return SQLPlan(
                "SELECT module_id, COUNT(*) AS ticket_count FROM tickets WHERE priority IN ('high', 'urgent') AND status IN ('open', 'pending') GROUP BY module_id",
                "统计高优先级未关闭工单的模块分布。",
            )
        return SQLPlan("SELECT category, COUNT(*) AS ticket_count FROM tickets GROUP BY category", "统计各类别工单数量。")

    def draft(self, question: str, evidence: list[RetrievedEvidence], result: QueryResult | None, sql_error: str | None) -> AnalysisDraft:
        if result is None:
            return AnalysisDraft("未形成统计结论。", f"受控 SQL 未执行：{sql_error or '未知原因'}")
        return AnalysisDraft(
            f"已基于 {result.row_count} 条受控统计结果和 {len(evidence)} 条候选证据生成初步运营分析。",
            "候选检索证据不等同于因果事实；结论仅适用于当前合成数据与查询口径。",
        )

    def review(self, question: str, evidence: list[RetrievedEvidence], result: QueryResult | None, draft: AnalysisDraft) -> ReviewDecision:
        return "approved" if result is not None else "revise_sql"
