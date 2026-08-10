"""Fixed, transparent evaluation loaders and SQL-safety runner; no metrics are fabricated without a real run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.agent_workflow import WorkflowResult
from app.services.sql_safety import SQLSafetyError, validate_readonly_select


ROOT = Path(__file__).resolve().parents[2]
QUESTION_SET_PATH = ROOT / "evaluation_sets" / "synthetic_operations_v1.json"
SQL_SAFETY_SET_PATH = ROOT / "evaluation_sets" / "sql_safety_v1.json"


def load_question_set(path: Path = QUESTION_SET_PATH) -> dict[str, Any]:
    """Load the public fixed question definitions without executing a model or query."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions")
    if not isinstance(questions, list) or not 15 <= len(questions) <= 20:
        raise ValueError("固定问题集必须包含 15 至 20 条问题")
    ids = [item.get("id") for item in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("固定问题集 ID 不能重复")
    return payload


def evaluate_sql_safety(path: Path = SQL_SAFETY_SET_PATH) -> dict[str, Any]:
    """Run each fixed candidate through the actual AST gate and retain only case ID and non-sensitive result facts."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in payload["cases"]:
        try:
            result = validate_readonly_select(case["sql"])
            actual_allowed = True
            detail = {"tables": list(result.tables), "max_rows": result.max_rows}
        except SQLSafetyError as error:
            actual_allowed = False
            detail = {"rejection": str(error)}
        results.append({"id": case["id"], "expected_allowed": case["allowed"], "actual_allowed": actual_allowed, "passed": case["allowed"] == actual_allowed, **detail})
    return {
        "evaluation_set": payload["version"],
        "total": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "results": results,
    }


def score_agent_result(question: dict[str, Any], result: WorkflowResult) -> dict[str, Any]:
    """Score observable workflow facts without retaining a question, SQL, rows, or conclusion.

    This is intentionally not a semantic judge of model prose.  It reports only
    pre-labelled evidence/table expectations and deterministic workflow outcomes
    from the fixed synthetic corpus.
    """

    expected_source_types = set(question.get("expected_source_types", []))
    actual_source_types = {item.source_type for item in result.evidence}
    expected_tables = set(question.get("required_sql_tables", []))
    actual_tables = set(result.query_result.tables) if result.query_result else set()
    sql_audit_statuses = [audit["status"] for audit in result.sql_audits]
    return {
        "id": question["id"],
        "status": result.status,
        "duration_ms": sum(trace["duration_ms"] for trace in result.trace),
        "expected_source_types": sorted(expected_source_types),
        "actual_source_types": sorted(actual_source_types),
        "evidence_hit": bool(actual_source_types & expected_source_types) if expected_source_types else None,
        "expected_sql_tables": sorted(expected_tables),
        "executed_sql_tables": sorted(actual_tables),
        "sql_table_match": expected_tables.issubset(actual_tables) if expected_tables else None,
        "query_executed": result.query_result is not None,
        "sql_audit_statuses": sql_audit_statuses,
        "sql_revisions": result.sql_revisions,
        "conclusion_revisions": result.conclusion_revisions,
    }


def summarize_agent_scores(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate fixed-set operational metrics while leaving prose correctness unclaimed."""

    total = len(results)
    evidence_scored = [item for item in results if item["evidence_hit"] is not None]
    sql_scored = [item for item in results if item["sql_table_match"] is not None]
    executed = [item for item in results if item["query_executed"]]
    durations = [int(item["duration_ms"]) for item in results if isinstance(item["duration_ms"], int)]
    statuses = {status: sum(1 for item in results if item["status"] == status) for status in ("completed", "limited", "failed")}
    return {
        "total_questions": total,
        "status_counts": statuses,
        "evidence_scored_questions": len(evidence_scored),
        "evidence_hits": sum(bool(item["evidence_hit"]) for item in evidence_scored),
        "evidence_hit_rate": round(sum(bool(item["evidence_hit"]) for item in evidence_scored) / len(evidence_scored), 4)
        if evidence_scored
        else None,
        "sql_scored_questions": len(sql_scored),
        "sql_table_matches": sum(bool(item["sql_table_match"]) for item in sql_scored),
        "sql_table_match_rate": round(sum(bool(item["sql_table_match"]) for item in sql_scored) / len(sql_scored), 4)
        if sql_scored
        else None,
        "bounded_query_executions": len(executed),
        "bounded_query_execution_rate": round(len(executed) / total, 4) if total else None,
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "semantic_conclusion_scoring": "not_automated",
    }
