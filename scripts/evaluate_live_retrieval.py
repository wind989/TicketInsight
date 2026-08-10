"""Run a transparent retrieval-only baseline over the fixed synthetic question set."""

from __future__ import annotations

import json
import os
from pathlib import Path

from qdrant_client import QdrantClient

from app.core.database import SessionLocal
from app.services.evaluation import load_question_set
from app.services.retrieval import LocalBGEEmbedder, QdrantEvidenceIndex, records_from_database


def main() -> None:
    qdrant_url = os.getenv("TICKETINSIGHT_QDRANT_URL")
    if not qdrant_url:
        raise SystemExit("TICKETINSIGHT_QDRANT_URL must point to the explicitly approved local Qdrant service")

    with SessionLocal() as session:
        records = records_from_database(session)
    if not records:
        raise SystemExit("no synthetic evidence records found; seed the dedicated database first")

    embedder = LocalBGEEmbedder()
    index = QdrantEvidenceIndex(QdrantClient(url=qdrant_url, timeout=10), embedder)
    index.upsert(records)
    question_set = load_question_set()

    results: list[dict[str, object]] = []
    scored = 0
    top1_hits = 0
    recall_hits = 0
    for item in question_set["questions"]:
        expected = list(item["expected_source_types"])
        evidence = index.search(item["question"], category=item["category"], limit=3)
        source_types = [candidate.source_type for candidate in evidence]
        if expected:
            scored += 1
            top1_hit = bool(source_types and source_types[0] in expected)
            recall_hit = any(source_type in expected for source_type in source_types)
            top1_hits += int(top1_hit)
            recall_hits += int(recall_hit)
        else:
            top1_hit = None
            recall_hit = None
        results.append(
            {
                "id": item["id"],
                "expected_source_types": expected,
                "actual_source_types": source_types,
                "top1_hit": top1_hit,
                "recall_at_3_hit": recall_hit,
            }
        )

    report = {
        "mode": "local_synthetic_retrieval_only",
        "evaluation_set": question_set["version"],
        "embedding_model": embedder.model_name,
        "embedding_dimension": embedder.dimension,
        "indexed_records": len(records),
        "scored_questions": scored,
        "top1_hits": top1_hits,
        "top1_rate": round(top1_hits / scored, 4) if scored else None,
        "recall_at_3_hits": recall_hits,
        "recall_at_3_rate": round(recall_hits / scored, 4) if scored else None,
        "results": results,
    }
    report_path = Path("reports/live_retrieval_evaluation.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("scored_questions", "top1_hits", "top1_rate", "recall_at_3_hits", "recall_at_3_rate")}))


if __name__ == "__main__":
    main()
