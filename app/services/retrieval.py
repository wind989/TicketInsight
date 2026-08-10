"""Evidence retrieval adapters with a deterministic fake for tests and an opt-in local BGE adapter."""

from __future__ import annotations

import hashlib
import os
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ServiceKnowledge, Ticket


COLLECTION_NAME = "ticketinsight_evidence_v1"
LOCAL_BGE_MODEL = "BAAI/bge-small-zh-v1.5"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_CACHE_DIR = PROJECT_ROOT / ".model-cache"
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def local_model_cache_dir() -> Path:
    """Return the configurable cache location for weights loaded without network access."""

    configured = os.getenv("TICKETINSIGHT_MODEL_CACHE_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_MODEL_CACHE_DIR


class Embedder(Protocol):
    model_name: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EvidenceRecord:
    source_type: str
    source_id: int
    title: str
    text_redacted: str
    category: str
    module_id: int | None


@dataclass(frozen=True)
class RetrievedEvidence:
    source_type: str
    source_id: int
    title: str
    excerpt_redacted: str
    category: str
    module_id: int | None
    score: float
    embedding_model: str
    embedding_dimension: int


class DeterministicTestEmbedder:
    """Offline, non-semantic test embedder; it is never presented as the BGE production model."""

    model_name = "deterministic-test-embedder-v1"

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            values = [0.0] * self.dimension
            tokens = TOKEN_RE.findall(text.lower())
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                position = int.from_bytes(digest[:4], "big") % self.dimension
                values[position] += 1.0 if digest[4] % 2 else -1.0
            magnitude = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / magnitude for value in values])
        return vectors


class LocalBGEEmbedder:
    """Load only a previously downloaded local BGE model; network download is deliberately not implicit."""

    def __init__(self, model_name: str = LOCAL_BGE_MODEL, model_cache_dir: str | Path | None = None) -> None:
        cache_dir = Path(model_cache_dir).expanduser().resolve() if model_cache_dir else local_model_cache_dir()
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError("未安装 sentence-transformers；未尝试下载本地 BGE 模型") from error
        try:
            self._model = SentenceTransformer(model_name, cache_folder=str(cache_dir), local_files_only=True)
        except Exception as error:
            raise RuntimeError("本地 BGE 模型不可用；拒绝自动下载") from error
        self.model_name = model_name
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, vector)) for vector in vectors]


class QdrantEvidenceIndex:
    """One collection for redacted ticket and service-knowledge evidence; no implicit deletion or recreation."""

    def __init__(self, client: QdrantClient, embedder: Embedder, collection_name: str = COLLECTION_NAME) -> None:
        self.client = client
        self.embedder = embedder
        self.collection_name = collection_name

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            collection = self.client.get_collection(self.collection_name)
            configured_size = collection.config.params.vectors.size
            if configured_size != self.embedder.dimension:
                raise RuntimeError("既有 Qdrant collection 维度不匹配；拒绝自动删除或重建")
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=self.embedder.dimension, distance=models.Distance.COSINE),
        )

    @staticmethod
    def _point_id(record: EvidenceRecord) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ticketinsight:{record.source_type}:{record.source_id}"))

    def upsert(self, records: Sequence[EvidenceRecord]) -> int:
        """Index only de-identified texts and metadata; update is deterministic by source type and ID."""

        if not records:
            return 0
        self.ensure_collection()
        vectors = self.embedder.embed([record.text_redacted for record in records])
        if any(len(vector) != self.embedder.dimension for vector in vectors):
            raise RuntimeError("Embedding 维度与索引配置不一致")
        points = [
            models.PointStruct(
                id=self._point_id(record),
                vector=vector,
                payload={
                    "source_type": record.source_type,
                    "source_id": record.source_id,
                    "title": record.title,
                    "excerpt_redacted": record.text_redacted[:500],
                    "category": record.category,
                    "module_id": record.module_id,
                    "embedding_model": self.embedder.model_name,
                    "embedding_dimension": self.embedder.dimension,
                },
            )
            for record, vector in zip(records, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def search(
        self,
        question: str,
        *,
        limit: int = 5,
        category: str | None = None,
        module_id: int | None = None,
    ) -> list[RetrievedEvidence]:
        """Return only collection-backed candidates; these are evidence, not statistical conclusions."""

        if not question.strip():
            raise ValueError("检索问题不能为空")
        if not self.client.collection_exists(self.collection_name):
            return []
        conditions: list[models.FieldCondition] = []
        if category:
            conditions.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
        if module_id is not None:
            conditions.append(models.FieldCondition(key="module_id", match=models.MatchValue(value=module_id)))
        result = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embedder.embed([question])[0],
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=min(max(limit, 1), 20),
            with_payload=True,
            with_vectors=False,
        )
        evidence: list[RetrievedEvidence] = []
        for point in result.points:
            payload = point.payload or {}
            evidence.append(
                RetrievedEvidence(
                    source_type=str(payload["source_type"]),
                    source_id=int(payload["source_id"]),
                    title=str(payload["title"]),
                    excerpt_redacted=str(payload["excerpt_redacted"]),
                    category=str(payload["category"]),
                    module_id=int(payload["module_id"]) if payload.get("module_id") is not None else None,
                    score=float(point.score),
                    embedding_model=str(payload["embedding_model"]),
                    embedding_dimension=int(payload["embedding_dimension"]),
                )
            )
        return evidence


def records_from_database(session: Session) -> list[EvidenceRecord]:
    """Construct the unified P1 evidence set from P0's redacted tables without logging their contents."""

    records = [
        EvidenceRecord(
            source_type="ticket",
            source_id=ticket.id,
            title=ticket.title,
            text_redacted=f"{ticket.title}\n{ticket.body_redacted}",
            category=ticket.category,
            module_id=ticket.module_id,
        )
        for ticket in session.scalars(select(Ticket).order_by(Ticket.id))
    ]
    records.extend(
        EvidenceRecord(
            source_type=knowledge.source_type,
            source_id=knowledge.id,
            title=knowledge.title,
            text_redacted=f"{knowledge.title}\n{knowledge.body_redacted}",
            category=knowledge.category,
            module_id=knowledge.module_id,
        )
        for knowledge in session.scalars(select(ServiceKnowledge).order_by(ServiceKnowledge.id))
    )
    return records
