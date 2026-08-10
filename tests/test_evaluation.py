"""Fixed evaluation assets remain transparent and the safety report executes the real gate."""

from __future__ import annotations

from app.services.agent_workflow import WorkflowResult
from app.services.evaluation import evaluate_sql_safety, load_question_set, score_agent_result, summarize_agent_scores
from app.services.readonly_query import QueryResult
from app.services.retrieval import RetrievedEvidence


def test_fixed_question_set_has_fifteen_unique_deidentified_cases():
    question_set = load_question_set()

    assert question_set["version"] == "synthetic-operations-v1"
    assert len(question_set["questions"]) == 15
    assert all("anon-" not in item["question"] for item in question_set["questions"])


def test_sql_safety_fixed_set_runs_through_the_real_ast_gate():
    report = evaluate_sql_safety()

    assert report["total"] == 19
    assert report["passed"] == 19
    assert all("sql" not in result for result in report["results"])


def test_agent_score_records_only_fixed_expectations_and_observable_safe_facts():
    question = load_question_set()["questions"][0]
    result = WorkflowResult(
        status="completed",
        evidence=[RetrievedEvidence("ticket", 8, "safe title", "safe excerpt", "payment", 1, 0.9, "fake", 64)],
        sql_candidate="SELECT id FROM tickets LIMIT 1",
        query_result=QueryResult([], 0, 3, "SELECT id FROM tickets LIMIT 1", "SELECT id FROM tickets LIMIT 1", ("tickets",)),
        conclusion="Never persisted in the evaluation report.",
        limitations="Synthetic test.",
        trace=[{"node": "review", "status": "approved", "duration_ms": 7}],
        sql_audits=[{"status": "executed", "audit_sql": "SELECT id FROM tickets LIMIT 1", "rejection_reason": None, "duration_ms": 3, "row_count": 0}],
        sql_revisions=0,
        conclusion_revisions=0,
    )

    scored = score_agent_result(question, result)
    summary = summarize_agent_scores([scored])

    assert scored["id"] == "Q01"
    assert scored["evidence_hit"] is True
    assert scored["sql_table_match"] is True
    assert "question" not in scored and "conclusion" not in scored and "sql_candidate" not in scored
    assert summary["bounded_query_execution_rate"] == 1.0
    assert summary["semantic_conclusion_scoring"] == "not_automated"
