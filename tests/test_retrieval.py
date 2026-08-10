"""P1 isolation tests using a real in-memory Qdrant collection and a clearly labelled fake embedder."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.services.retrieval import DeterministicTestEmbedder, EvidenceRecord, LocalBGEEmbedder, QdrantEvidenceIndex, records_from_database
from app.services.seed import seed_synthetic_data


def test_qdrant_in_memory_returns_locatable_redacted_evidence():
    index = QdrantEvidenceIndex(QdrantClient(":memory:"), DeterministicTestEmbedder())
    indexed = index.upsert(
        [
            EvidenceRecord("ticket", 11, "支付回调延迟", "支付回调队列延迟导致订单状态未更新。", "payment", 1),
            EvidenceRecord("sop", 12, "登录处理指引", "核对验证码和登录状态。", "login", 2),
        ]
    )

    assert indexed == 2
    results = index.search("支付回调状态", category="payment")
    assert results[0].source_type == "ticket"
    assert results[0].source_id == 11
    assert results[0].embedding_model == "deterministic-test-embedder-v1"
    assert "支付" in results[0].excerpt_redacted


def test_existing_collection_dimension_mismatch_never_triggers_automatic_recreation():
    client = QdrantClient(":memory:")
    first_index = QdrantEvidenceIndex(client, DeterministicTestEmbedder(dimension=8))
    first_index.ensure_collection()
    second_index = QdrantEvidenceIndex(client, DeterministicTestEmbedder(dimension=16))

    try:
        second_index.ensure_collection()
    except RuntimeError as error:
        assert "拒绝自动删除或重建" in str(error)
    else:
        raise AssertionError("expected dimension mismatch to be rejected")


def test_p0_synthetic_records_can_fill_the_unified_in_memory_evidence_collection():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_synthetic_data(session)
        records = records_from_database(session)

    index = QdrantEvidenceIndex(QdrantClient(":memory:"), DeterministicTestEmbedder())
    assert index.upsert(records) == 11
    assert index.search("支付回调", category="payment")


def test_local_bge_adapter_fails_closed_when_the_model_is_not_in_the_explicit_cache(tmp_path):
    try:
        LocalBGEEmbedder(model_cache_dir=tmp_path)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the test environment must not auto-download an embedding model")
