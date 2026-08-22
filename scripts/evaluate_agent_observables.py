"""Evaluate fixed graph mechanics offline without a model, network, or real data."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.agent_workflow import AnalysisDraft, SQLPlan, TicketInsightWorkflow
from app.services.evaluation import load_question_set, score_agent_observables, summarize_agent_observables
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence
from app.services.sql_safety import validate_readonly_select


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "agent_observables_evaluation.json"


class ObservablePlanner:
    def plan(self, question, evidence, prior_error):
        return SQLPlan(
            "SELECT category, COUNT(id) AS ticket_count FROM tickets GROUP BY category ORDER BY ticket_count DESC LIMIT 20",
            "固定安全统计，用于验证图的角色路径。",
        )


class ObservableAdvisor:
    def draft(self, question, evidence, result, sql_error):
        return AnalysisDraft("固定受控查询已完成。", "该离线报告只评估工作流机制，不判断结论语义。")


class ObservableReviewer:
    def review(self, question, evidence, result, draft):
        return "approved"


def _query(sql: str) -> QueryResult:
    validated = validate_readonly_select(sql)
    return QueryResult(
        [{"category": "payment", "ticket_count": 1}],
        1,
        0,
        validated.sql,
        validated.audit_sql,
        validated.tables,
    )


def evaluate() -> dict[str, object]:
    question_set = load_question_set()
    workflow = TicketInsightWorkflow(
        retrieval_tool=lambda _: [RetrievedEvidence("ticket", 1, "synthetic evidence", "bounded excerpt", "payment", 1, 0.8, "fake", 64)],
        sql_planner=ObservablePlanner(),
        query_tool=_query,
        attribution_advisor=ObservableAdvisor(),
        reviewer=ObservableReviewer(),
    )
    scores = [
        score_agent_observables(workflow.run(item["question"], run_id=f"offline-{item['id']}"))
        for item in question_set["questions"]
    ]
    return {
        "evaluation_set": question_set["version"],
        "mode": "offline_fake_agent_mechanics",
        "report": summarize_agent_observables(scores),
    }


def main() -> None:
    report = evaluate()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
