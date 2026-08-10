"""Run the fixed synthetic set through the real bounded workflow after explicit cost approval."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from app.core.database import SessionLocal
from app.services.analysis_runs import run_and_persist
from app.services.evaluation import load_question_set, score_agent_result, summarize_agent_scores
from app.services.production_runtime import build_production_workflow
from app.services.retrieval import LocalBGEEmbedder, QdrantEvidenceIndex, records_from_database


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-real-llm",
        action="store_true",
        help="required because this performs paid, configured LLM calls against local synthetic data",
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N fixed questions for a bounded smoke check")
    parser.add_argument("--ids", nargs="+", help="run named fixed question IDs only, for a bounded regression check")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "live_agent_evaluation.json",
        help="local JSON output path; use a distinct path for a smoke run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_real_llm:
        raise SystemExit("Refusing to start paid model calls. Re-run with --confirm-real-llm after reviewing the local synthetic scope.")

    question_set = load_question_set()
    questions = list(question_set["questions"])
    if args.ids:
        if args.limit is not None:
            raise SystemExit("Use either --ids or --limit, not both")
        requested_ids = set(args.ids)
        known_ids = {item["id"] for item in questions}
        unknown_ids = requested_ids - known_ids
        if unknown_ids:
            raise SystemExit(f"Unknown fixed question IDs: {', '.join(sorted(unknown_ids))}")
        questions = [item for item in questions if item["id"] in requested_ids]
    if args.limit is not None:
        if not 1 <= args.limit <= len(questions):
            raise SystemExit(f"--limit must be between 1 and {len(questions)}")
        questions = questions[: args.limit]

    load_dotenv(ROOT / ".env", override=False)
    qdrant_url = os.getenv("TICKETINSIGHT_QDRANT_URL")
    if not qdrant_url:
        raise SystemExit("TICKETINSIGHT_QDRANT_URL must name the approved local Qdrant service")
    with SessionLocal() as session:
        records = records_from_database(session)
    if not records:
        raise SystemExit("No synthetic evidence records found; seed the dedicated TicketInsight database first")

    # Indexing is deterministic local BGE/Qdrant work.  It runs before model calls
    # so the evaluation report can state the exact evidence-record count.
    index = QdrantEvidenceIndex(QdrantClient(url=qdrant_url, timeout=10), LocalBGEEmbedder())
    indexed_records = index.upsert(records)
    workflow, retriever_model = build_production_workflow()

    results: list[dict[str, object]] = []
    for item in questions:
        with SessionLocal() as session:
            try:
                persisted = run_and_persist(session, workflow, item["question"], retriever_model=retriever_model)
            except Exception:
                # The durable run is marked failed by run_and_persist.  Do not copy
                # provider errors, SQL, question text, or exception details to the
                # public evaluation artifact.
                results.append(
                    {
                        "id": item["id"],
                        "status": "failed",
                        "duration_ms": None,
                        "expected_source_types": sorted(item["expected_source_types"]),
                        "actual_source_types": [],
                        "evidence_hit": False if item["expected_source_types"] else None,
                        "expected_sql_tables": sorted(item["required_sql_tables"]),
                        "executed_sql_tables": [],
                        "sql_table_match": False if item["required_sql_tables"] else None,
                        "query_executed": False,
                        "sql_audit_statuses": [],
                        "sql_revisions": 0,
                        "conclusion_revisions": 0,
                    }
                )
            else:
                results.append(score_agent_result(item, persisted.result))

    report = {
        "mode": "local_synthetic_real_agent",
        "evaluation_set": question_set["version"],
        "dataset": question_set["dataset"],
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "retriever_model": retriever_model,
        "indexed_records": indexed_records,
        "requested_questions": len(questions),
        "model_call_bound_per_question": 6,
        "summary": summarize_agent_scores(results),
        "results": results,
        "limitations": [
            "Runs only on TicketInsight fixed synthetic/de-identified data.",
            "Metrics score retrieval/type and required-table expectations, not semantic correctness of model prose.",
            "No question text, SQL, query rows, evidence excerpts, model responses, credentials, or conclusions are copied here.",
        ],
    }
    path = args.output
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(path),
                "questions": report["requested_questions"],
                "summary": report["summary"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
