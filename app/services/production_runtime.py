"""Fail-closed construction of the real analysis workflow from separately scoped local configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from app.core.config import get_llm_timeout_seconds
from app.services.agent_workflow import TicketInsightWorkflow
from app.services.llm_advisor import OpenAICompatibleAdvisor
from app.services.readonly_query import ReadonlyQueryExecutor, build_readonly_engine
from app.services.retrieval import COLLECTION_NAME, LOCAL_BGE_MODEL, LocalBGEEmbedder, QdrantEvidenceIndex


def build_production_workflow() -> tuple[TicketInsightWorkflow, str]:
    """Build the graph only if all optional runtime components are explicitly configured and locally available."""

    load_dotenv(override=False)
    qdrant_url = os.getenv("TICKETINSIGHT_QDRANT_URL")
    endpoint = os.getenv("TICKETINSIGHT_DEEPSEEK_BASE_URL")
    api_key = os.getenv("TICKETINSIGHT_DEEPSEEK_API_KEY")
    model = os.getenv("TICKETINSIGHT_DEEPSEEK_MODEL")
    if not all([qdrant_url, endpoint, api_key, model]):
        raise RuntimeError("分析运行时未完整配置 Qdrant 或模型；拒绝降级到未知目标")
    embedder = LocalBGEEmbedder(os.getenv("TICKETINSIGHT_EMBEDDING_MODEL", LOCAL_BGE_MODEL))
    index = QdrantEvidenceIndex(QdrantClient(url=qdrant_url, timeout=5), embedder, collection_name=COLLECTION_NAME)
    advisor = OpenAICompatibleAdvisor(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        timeout_seconds=get_llm_timeout_seconds(),
    )
    executor = ReadonlyQueryExecutor(build_readonly_engine())
    workflow = TicketInsightWorkflow(
        retrieval_tool=lambda question: index.search(question),
        sql_planner=advisor,
        query_tool=executor.execute,
        attribution_advisor=advisor,
        reviewer=advisor,
    )
    return workflow, embedder.model_name
