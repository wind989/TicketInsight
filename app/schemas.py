"""API contracts that enforce synthetic/de-identified P0 data at the boundary."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Category = Literal["payment", "login", "order", "refund", "logistics", "account"]
Priority = Literal["low", "medium", "high", "urgent"]
TicketStatus = Literal["open", "pending", "resolved", "closed"]
CustomerTier = Literal["standard", "vip", "enterprise"]
ModuleStatus = Literal["active", "deprecated"]
KnowledgeSource = Literal["faq", "sop", "known_issue", "category_definition"]
EventType = Literal["created", "assigned", "responded", "resolved", "reopened"]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
ANONYMOUS_ID_RE = re.compile(r"^anon-[A-Za-z0-9_-]{4,32}$")


def reject_pii_text(value: str | None) -> str | None:
    """Reject clear PII patterns instead of retaining unredacted source text in P0 storage."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("文本不能为空")
    if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned):
        raise ValueError("只接受脱敏文本，不能包含邮箱或手机号")
    return cleaned


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(BaseModel):
    anonymous_id: str = Field(min_length=9, max_length=40)
    tier: CustomerTier = "standard"

    @field_validator("anonymous_id")
    @classmethod
    def validate_anonymous_id(cls, value: str) -> str:
        if not ANONYMOUS_ID_RE.fullmatch(value):
            raise ValueError("anonymous_id 必须使用 anon- 前缀的匿名标识")
        return value


class CustomerUpdate(BaseModel):
    tier: CustomerTier | None = None


class CustomerRead(ORMModel):
    id: int
    anonymous_id: str
    tier: CustomerTier
    created_at: datetime


class ProductModuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=1000)
    status: ModuleStatus = "active"

    _description_safe = field_validator("description")(reject_pii_text)


class ProductModuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, min_length=2, max_length=1000)
    status: ModuleStatus | None = None

    _description_safe = field_validator("description")(reject_pii_text)


class ProductModuleRead(ORMModel):
    id: int
    name: str
    description: str
    status: ModuleStatus
    created_at: datetime


class SLAPolicyCreate(BaseModel):
    category: Category
    priority: Priority
    response_minutes: int = Field(gt=0, le=10080)
    resolution_minutes: int = Field(gt=0, le=43200)
    active: bool = True


class SLAPolicyUpdate(BaseModel):
    response_minutes: int | None = Field(default=None, gt=0, le=10080)
    resolution_minutes: int | None = Field(default=None, gt=0, le=43200)
    active: bool | None = None


class SLAPolicyRead(ORMModel):
    id: int
    category: Category
    priority: Priority
    response_minutes: int
    resolution_minutes: int
    active: bool
    created_at: datetime


class TicketCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body_redacted: str = Field(min_length=2, max_length=4000)
    category: Category
    priority: Priority
    status: TicketStatus = "open"
    customer_id: int = Field(gt=0)
    module_id: int = Field(gt=0)
    created_at: datetime
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None

    _title_safe = field_validator("title")(reject_pii_text)
    _body_safe = field_validator("body_redacted")(reject_pii_text)


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    body_redacted: str | None = Field(default=None, min_length=2, max_length=4000)
    category: Category | None = None
    priority: Priority | None = None
    status: TicketStatus | None = None
    module_id: int | None = Field(default=None, gt=0)
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None

    _title_safe = field_validator("title")(reject_pii_text)
    _body_safe = field_validator("body_redacted")(reject_pii_text)


class TicketRead(ORMModel):
    id: int
    title: str
    body_redacted: str
    category: Category
    priority: Priority
    status: TicketStatus
    customer_id: int
    module_id: int
    created_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None


class TicketEventCreate(BaseModel):
    event_type: EventType
    occurred_at: datetime
    actor_group: str = Field(min_length=2, max_length=40)
    note_redacted: str | None = Field(default=None, min_length=2, max_length=1000)

    _note_safe = field_validator("note_redacted")(reject_pii_text)


class TicketEventUpdate(BaseModel):
    event_type: EventType | None = None
    occurred_at: datetime | None = None
    actor_group: str | None = Field(default=None, min_length=2, max_length=40)
    note_redacted: str | None = Field(default=None, min_length=2, max_length=1000)

    _note_safe = field_validator("note_redacted")(reject_pii_text)


class TicketEventRead(ORMModel):
    id: int
    ticket_id: int
    event_type: EventType
    occurred_at: datetime
    actor_group: str
    note_redacted: str | None


class ServiceKnowledgeCreate(BaseModel):
    source_type: KnowledgeSource
    title: str = Field(min_length=2, max_length=200)
    body_redacted: str = Field(min_length=2, max_length=4000)
    category: Category
    module_id: int | None = Field(default=None, gt=0)
    version: str = Field(min_length=1, max_length=40)

    _title_safe = field_validator("title")(reject_pii_text)
    _body_safe = field_validator("body_redacted")(reject_pii_text)


class ServiceKnowledgeUpdate(BaseModel):
    source_type: KnowledgeSource | None = None
    title: str | None = Field(default=None, min_length=2, max_length=200)
    body_redacted: str | None = Field(default=None, min_length=2, max_length=4000)
    category: Category | None = None
    module_id: int | None = Field(default=None, gt=0)
    version: str | None = Field(default=None, min_length=1, max_length=40)

    _title_safe = field_validator("title")(reject_pii_text)
    _body_safe = field_validator("body_redacted")(reject_pii_text)


class ServiceKnowledgeRead(ORMModel):
    id: int
    source_type: KnowledgeSource
    title: str
    body_redacted: str
    category: Category
    module_id: int | None
    version: str
    created_at: datetime


class SeedSummary(BaseModel):
    created: bool
    customers: int
    product_modules: int
    sla_policies: int
    tickets: int
    ticket_events: int
    service_knowledge: int


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)

    _question_safe = field_validator("question")(reject_pii_text)


class AnalysisRunStarted(BaseModel):
    """A subscription handle only; this never contains a draft or final report."""

    id: str
    status: Literal["running"]
    events_url: str


class AnalysisFeedbackCreate(BaseModel):
    helpful: bool
    reason_redacted: str | None = Field(default=None, min_length=2, max_length=1000)

    _reason_safe = field_validator("reason_redacted")(reject_pii_text)


class AnalysisEvidenceRead(ORMModel):
    source_type: str
    business_id: int
    title: str
    excerpt_redacted: str
    score: float


class SQLAuditRead(ORMModel):
    attempt_index: int
    status: str
    audit_sql: str | None
    rejection_reason: str | None
    duration_ms: int | None
    row_count: int | None


class AgentTraceRead(ORMModel):
    node: str
    status: str
    duration_ms: int


class AnalysisContextRead(BaseModel):
    """Aggregate-only per-run context; never expose checkpoint payloads."""

    scope: Literal["single_run"] = "single_run"
    checkpoint_scope: Literal["process_local_bounded"] = "process_local_bounded"
    checkpoint_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    query_row_count: int = Field(ge=0)
    sql_revisions: int = Field(ge=0, le=1)
    conclusion_revisions: int = Field(ge=0, le=1)
    review_decision: str | None = None


class AnalysisFeedbackRead(ORMModel):
    id: int
    helpful: bool
    reason_redacted: str | None
    created_at: datetime


class AnalysisReportRead(ORMModel):
    id: str
    question_redacted: str
    status: str
    graph_version: str
    retriever_model: str | None
    total_duration_ms: int | None
    conclusion: str | None
    limitations: str | None
    created_at: datetime
    completed_at: datetime | None
    context: AnalysisContextRead | None = None
    evidence: list[AnalysisEvidenceRead]
    sql_audits: list[SQLAuditRead]
    traces: list[AgentTraceRead]
