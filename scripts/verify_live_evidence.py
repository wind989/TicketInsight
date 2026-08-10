"""Verify local BGE retrieval and read-only SQL against the dedicated Docker services."""

from __future__ import annotations

import json
from pathlib import Path

from qdrant_client import QdrantClient

from app.core.database import SessionLocal
from app.services.readonly_query import ReadonlyQueryExecutor, build_readonly_engine
from app.services.retrieval import LocalBGEEmbedder, QdrantEvidenceIndex, records_from_database
from app.services.sql_safety import SQLSafetyError


def main() -> None:
    with SessionLocal() as session:
        records = records_from_database(session)
    if not records:
        raise SystemExit("no synthetic evidence records found; seed the dedicated database first")

    embedder = LocalBGEEmbedder()
    index = QdrantEvidenceIndex(QdrantClient(url="http://127.0.0.1:6333", timeout=10), embedder)
    indexed = index.upsert(records)
    evidence = index.search("支付回调延迟导致订单状态未更新", category="payment", limit=3)
    if not evidence or evidence[0].source_type != "ticket":
        raise SystemExit("live Qdrant retrieval did not return the expected synthetic payment evidence")

    executor = ReadonlyQueryExecutor(build_readonly_engine())
    query_result = executor.execute("SELECT id, status, priority, module_id FROM tickets ORDER BY id LIMIT 5")
    if query_result.row_count != 5 or query_result.tables != ("tickets",):
        raise SystemExit("read-only MySQL query did not return the expected bounded rows")
    try:
        executor.execute("SELECT id FROM tickets FOR UPDATE")
    except SQLSafetyError:
        unsafe_sql_rejected = True
    else:
        raise SystemExit("unsafe locking SQL was not rejected before execution")

    report_path = Path("reports/live_evidence_verification.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "mode": "local_synthetic_services",
                "embedding_model": embedder.model_name,
                "embedding_dimension": embedder.dimension,
                "indexed_records": indexed,
                "top_evidence": {
                    "source_type": evidence[0].source_type,
                    "source_id": evidence[0].source_id,
                    "category": evidence[0].category,
                    "embedding_dimension": evidence[0].embedding_dimension,
                },
                "readonly_query": {
                    "tables": query_result.tables,
                    "row_count": query_result.row_count,
                    "duration_ms": query_result.duration_ms,
                    "audit_sql": query_result.audit_sql,
                },
                "unsafe_locking_sql_rejected_before_execution": unsafe_sql_rejected,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"indexed_records": indexed, "evidence_source": evidence[0].source_type, "query_rows": query_result.row_count}))


if __name__ == "__main__":
    main()
