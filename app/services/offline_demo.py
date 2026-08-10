"""A deliberately labelled offline demonstration of the fixed workflow, without external services or credentials."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

from app.models import Base
from app.services.agent_workflow import TicketInsightWorkflow
from app.services.analysis_runs import run_and_persist
from app.services.fake_llm import FakeOperationsLLM
from app.services.readonly_query import ReadonlyQueryExecutor
from app.services.retrieval import DeterministicTestEmbedder, QdrantEvidenceIndex, records_from_database
from app.services.seed import seed_synthetic_data


def run_offline_demo(question: str = "为什么本周支付类投诉增加？") -> dict:
    """Run a full in-memory demonstration and return only redacted evidence/report fields with explicit limitations."""

    with TemporaryDirectory(prefix="ticketinsight-offline-demo-") as directory:
        database_url = f"sqlite:///{(Path(directory) / 'demo.db').as_posix()}"
        application_engine = create_engine(database_url, future=True)
        readonly_engine = create_engine(database_url, future=True)
        try:
            Base.metadata.create_all(application_engine)
            with Session(application_engine) as session:
                seed_synthetic_data(session)
                index = QdrantEvidenceIndex(QdrantClient(":memory:"), DeterministicTestEmbedder())
                index.upsert(records_from_database(session))
                fake_llm = FakeOperationsLLM()
                workflow = TicketInsightWorkflow(
                    retrieval_tool=lambda query: index.search(query),
                    sql_planner=fake_llm,
                    query_tool=ReadonlyQueryExecutor(readonly_engine).execute,
                    attribution_advisor=fake_llm,
                    reviewer=fake_llm,
                )
                persisted = run_and_persist(session, workflow, question, retriever_model="deterministic-test-embedder-v1")
                result = persisted.result
                report = {
                    "mode": "offline_fake",
                    "run_id": persisted.run_id,
                    "status": result.status,
                    "evidence": [{"source_type": item.source_type, "source_id": item.source_id, "score": item.score} for item in result.evidence],
                    "sql_audits": result.sql_audits,
                    "query_rows": result.query_result.rows if result.query_result else [],
                    "conclusion": result.conclusion,
                    "limitations": "本演示使用临时 SQLite、内存 Qdrant、确定性测试嵌入器和 Fake LLM；不代表真实 MySQL、BGE、Qdrant 服务或模型效果。 " + result.limitations,
                    "trace": result.trace,
                }
        finally:
            readonly_engine.dispose()
            application_engine.dispose()
        return report
