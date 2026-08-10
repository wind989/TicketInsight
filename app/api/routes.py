"""P0 CRUD endpoints for synthetic TicketInsight domain data."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import database
from app.core.database import get_session
from app.models import AgentTrace, AnalysisEvidence, AnalysisRun, Customer, ProductModule, SLAPolicy, SQLAudit, ServiceKnowledge, Ticket, TicketEvent
from app.schemas import (
    AnalysisFeedbackCreate, AnalysisFeedbackRead, AnalysisReportRead, AnalysisRequest, AnalysisRunStarted, CustomerCreate, CustomerRead,
    CustomerUpdate, ProductModuleCreate, ProductModuleRead, ProductModuleUpdate, SeedSummary, ServiceKnowledgeCreate,
    ServiceKnowledgeRead, ServiceKnowledgeUpdate, SLAPolicyCreate,
    SLAPolicyRead, SLAPolicyUpdate, TicketCreate, TicketEventCreate, TicketEventRead, TicketEventUpdate,
    TicketRead, TicketUpdate,
)
from app.services.seed import seed_synthetic_data
from app.services.analysis_runs import add_feedback, create_pending_run, execute_pending_run_with_progress, run_and_persist
from app.services.progress import ProgressEvent, progress_events
from app.services.production_runtime import build_production_workflow


router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]
PageOffset = Annotated[int, Query(ge=0)]
PageLimit = Annotated[int, Query(ge=1, le=200)]


def _get_or_404(session: Session, model: type[Any], item_id: int, label: str) -> Any:
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return item


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="数据冲突或关联数据不存在") from error


def _ensure_module(session: Session, module_id: int | None) -> None:
    if module_id is not None:
        _get_or_404(session, ProductModule, module_id, "产品模块")


@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED, tags=["customers"])
def create_customer(payload: CustomerCreate, session: SessionDep) -> Customer:
    item = Customer(**payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/customers", response_model=list[CustomerRead], tags=["customers"])
def list_customers(session: SessionDep, offset: PageOffset = 0, limit: PageLimit = 50) -> list[Customer]:
    return list(session.scalars(select(Customer).order_by(Customer.id).offset(offset).limit(limit)))


@router.get("/customers/{customer_id}", response_model=CustomerRead, tags=["customers"])
def get_customer(customer_id: int, session: SessionDep) -> Customer:
    return _get_or_404(session, Customer, customer_id, "客户")


@router.patch("/customers/{customer_id}", response_model=CustomerRead, tags=["customers"])
def update_customer(customer_id: int, payload: CustomerUpdate, session: SessionDep) -> Customer:
    item = _get_or_404(session, Customer, customer_id, "客户")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["customers"])
def delete_customer(customer_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, Customer, customer_id, "客户")
    if session.scalar(select(Ticket.id).where(Ticket.customer_id == customer_id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="该客户仍有关联工单，不能删除")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/product-modules", response_model=ProductModuleRead, status_code=status.HTTP_201_CREATED, tags=["product_modules"])
def create_module(payload: ProductModuleCreate, session: SessionDep) -> ProductModule:
    item = ProductModule(**payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/product-modules", response_model=list[ProductModuleRead], tags=["product_modules"])
def list_modules(session: SessionDep, offset: PageOffset = 0, limit: PageLimit = 50) -> list[ProductModule]:
    return list(session.scalars(select(ProductModule).order_by(ProductModule.id).offset(offset).limit(limit)))


@router.get("/product-modules/{module_id}", response_model=ProductModuleRead, tags=["product_modules"])
def get_module(module_id: int, session: SessionDep) -> ProductModule:
    return _get_or_404(session, ProductModule, module_id, "产品模块")


@router.patch("/product-modules/{module_id}", response_model=ProductModuleRead, tags=["product_modules"])
def update_module(module_id: int, payload: ProductModuleUpdate, session: SessionDep) -> ProductModule:
    item = _get_or_404(session, ProductModule, module_id, "产品模块")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/product-modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["product_modules"])
def delete_module(module_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, ProductModule, module_id, "产品模块")
    ticket_exists = session.scalar(select(Ticket.id).where(Ticket.module_id == module_id).limit(1)) is not None
    knowledge_exists = session.scalar(select(ServiceKnowledge.id).where(ServiceKnowledge.module_id == module_id).limit(1)) is not None
    if ticket_exists or knowledge_exists:
        raise HTTPException(status_code=409, detail="该模块仍有关联工单或服务知识，不能删除")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sla-policies", response_model=SLAPolicyRead, status_code=status.HTTP_201_CREATED, tags=["sla"])
def create_sla_policy(payload: SLAPolicyCreate, session: SessionDep) -> SLAPolicy:
    item = SLAPolicy(**payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/sla-policies", response_model=list[SLAPolicyRead], tags=["sla"])
def list_sla_policies(
    session: SessionDep,
    category: str | None = None,
    priority: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> list[SLAPolicy]:
    statement = select(SLAPolicy).order_by(SLAPolicy.id)
    if category:
        statement = statement.where(SLAPolicy.category == category)
    if priority:
        statement = statement.where(SLAPolicy.priority == priority)
    return list(session.scalars(statement.offset(offset).limit(limit)))


@router.get("/sla-policies/{policy_id}", response_model=SLAPolicyRead, tags=["sla"])
def get_sla_policy(policy_id: int, session: SessionDep) -> SLAPolicy:
    return _get_or_404(session, SLAPolicy, policy_id, "SLA策略")


@router.patch("/sla-policies/{policy_id}", response_model=SLAPolicyRead, tags=["sla"])
def update_sla_policy(policy_id: int, payload: SLAPolicyUpdate, session: SessionDep) -> SLAPolicy:
    item = _get_or_404(session, SLAPolicy, policy_id, "SLA策略")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/sla-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["sla"])
def delete_sla_policy(policy_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, SLAPolicy, policy_id, "SLA策略")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tickets", response_model=TicketRead, status_code=status.HTTP_201_CREATED, tags=["tickets"])
def create_ticket(payload: TicketCreate, session: SessionDep) -> Ticket:
    _get_or_404(session, Customer, payload.customer_id, "客户")
    _ensure_module(session, payload.module_id)
    item = Ticket(**payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/tickets", response_model=list[TicketRead], tags=["tickets"])
def list_tickets(
    session: SessionDep,
    category: str | None = None,
    priority: str | None = None,
    ticket_status: str | None = Query(default=None, alias="status"),
    customer_id: int | None = Query(default=None, gt=0),
    module_id: int | None = Query(default=None, gt=0),
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> list[Ticket]:
    statement = select(Ticket).order_by(Ticket.created_at.desc(), Ticket.id.desc())
    if category:
        statement = statement.where(Ticket.category == category)
    if priority:
        statement = statement.where(Ticket.priority == priority)
    if ticket_status:
        statement = statement.where(Ticket.status == ticket_status)
    if customer_id:
        statement = statement.where(Ticket.customer_id == customer_id)
    if module_id:
        statement = statement.where(Ticket.module_id == module_id)
    return list(session.scalars(statement.offset(offset).limit(limit)))


@router.get("/tickets/{ticket_id}", response_model=TicketRead, tags=["tickets"])
def get_ticket(ticket_id: int, session: SessionDep) -> Ticket:
    return _get_or_404(session, Ticket, ticket_id, "工单")


@router.patch("/tickets/{ticket_id}", response_model=TicketRead, tags=["tickets"])
def update_ticket(ticket_id: int, payload: TicketUpdate, session: SessionDep) -> Ticket:
    item = _get_or_404(session, Ticket, ticket_id, "工单")
    values = payload.model_dump(exclude_unset=True)
    _ensure_module(session, values.get("module_id"))
    for key, value in values.items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["tickets"])
def delete_ticket(ticket_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, Ticket, ticket_id, "工单")
    if session.scalar(select(TicketEvent.id).where(TicketEvent.ticket_id == ticket_id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="该工单仍有关联事件，不能删除")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/tickets/{ticket_id}/events", response_model=TicketEventRead, status_code=status.HTTP_201_CREATED, tags=["ticket_events"])
def create_ticket_event(ticket_id: int, payload: TicketEventCreate, session: SessionDep) -> TicketEvent:
    _get_or_404(session, Ticket, ticket_id, "工单")
    item = TicketEvent(ticket_id=ticket_id, **payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/tickets/{ticket_id}/events", response_model=list[TicketEventRead], tags=["ticket_events"])
def list_ticket_events(ticket_id: int, session: SessionDep, offset: PageOffset = 0, limit: PageLimit = 50) -> list[TicketEvent]:
    _get_or_404(session, Ticket, ticket_id, "工单")
    statement = select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.occurred_at, TicketEvent.id)
    return list(session.scalars(statement.offset(offset).limit(limit)))


@router.patch("/ticket-events/{event_id}", response_model=TicketEventRead, tags=["ticket_events"])
def update_ticket_event(event_id: int, payload: TicketEventUpdate, session: SessionDep) -> TicketEvent:
    item = _get_or_404(session, TicketEvent, event_id, "工单事件")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/ticket-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["ticket_events"])
def delete_ticket_event(event_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, TicketEvent, event_id, "工单事件")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/service-knowledge", response_model=ServiceKnowledgeRead, status_code=status.HTTP_201_CREATED, tags=["service_knowledge"])
def create_service_knowledge(payload: ServiceKnowledgeCreate, session: SessionDep) -> ServiceKnowledge:
    _ensure_module(session, payload.module_id)
    item = ServiceKnowledge(**payload.model_dump())
    session.add(item)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.get("/service-knowledge", response_model=list[ServiceKnowledgeRead], tags=["service_knowledge"])
def list_service_knowledge(
    session: SessionDep,
    source_type: str | None = None,
    category: str | None = None,
    module_id: int | None = Query(default=None, gt=0),
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> list[ServiceKnowledge]:
    statement = select(ServiceKnowledge).order_by(ServiceKnowledge.id)
    if source_type:
        statement = statement.where(ServiceKnowledge.source_type == source_type)
    if category:
        statement = statement.where(ServiceKnowledge.category == category)
    if module_id:
        statement = statement.where(ServiceKnowledge.module_id == module_id)
    return list(session.scalars(statement.offset(offset).limit(limit)))


@router.get("/service-knowledge/{knowledge_id}", response_model=ServiceKnowledgeRead, tags=["service_knowledge"])
def get_service_knowledge(knowledge_id: int, session: SessionDep) -> ServiceKnowledge:
    return _get_or_404(session, ServiceKnowledge, knowledge_id, "服务知识")


@router.patch("/service-knowledge/{knowledge_id}", response_model=ServiceKnowledgeRead, tags=["service_knowledge"])
def update_service_knowledge(knowledge_id: int, payload: ServiceKnowledgeUpdate, session: SessionDep) -> ServiceKnowledge:
    item = _get_or_404(session, ServiceKnowledge, knowledge_id, "服务知识")
    values = payload.model_dump(exclude_unset=True)
    _ensure_module(session, values.get("module_id"))
    for key, value in values.items():
        setattr(item, key, value)
    _commit_or_conflict(session)
    session.refresh(item)
    return item


@router.delete("/service-knowledge/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["service_knowledge"])
def delete_service_knowledge(knowledge_id: int, session: SessionDep) -> Response:
    item = _get_or_404(session, ServiceKnowledge, knowledge_id, "服务知识")
    session.delete(item)
    _commit_or_conflict(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/demo/seed", response_model=SeedSummary, tags=["demo"])
def seed_demo_data(session: SessionDep) -> dict[str, int | bool]:
    """Load fixed synthetic data; repeated calls are intentionally idempotent."""

    return seed_synthetic_data(session)


def _analysis_report(session: Session, run_id: str) -> dict[str, Any]:
    run = _get_or_404(session, AnalysisRun, run_id, "分析运行")
    return {
        "id": run.id,
        "question_redacted": run.question_redacted,
        "status": run.status,
        "graph_version": run.graph_version,
        "retriever_model": run.retriever_model,
        "total_duration_ms": run.total_duration_ms,
        "conclusion": run.conclusion,
        "limitations": run.limitations,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "evidence": list(session.scalars(select(AnalysisEvidence).where(AnalysisEvidence.run_id == run_id).order_by(AnalysisEvidence.id))),
        "sql_audits": list(session.scalars(select(SQLAudit).where(SQLAudit.run_id == run_id).order_by(SQLAudit.attempt_index))),
        "traces": list(session.scalars(select(AgentTrace).where(AgentTrace.run_id == run_id).order_by(AgentTrace.id))),
    }


@router.post("/analysis-runs", response_model=AnalysisReportRead, status_code=status.HTTP_201_CREATED, tags=["analysis"])
def create_analysis_run(payload: AnalysisRequest, session: SessionDep) -> dict[str, Any]:
    """Run only the fixed production graph; missing Qdrant/model/read-only credentials fails closed."""

    try:
        workflow, retriever_model = build_production_workflow()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        persisted = run_and_persist(session, workflow, payload.question, retriever_model=retriever_model)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _analysis_report(session, persisted.run_id)


SSE_POLL_SECONDS = 1.0
SSE_HEARTBEAT_SECONDS = 10.0
TERMINAL_RUN_STATUSES = {"completed", "limited", "failed"}


def _sse_frame(event: ProgressEvent) -> str:
    """Serialize the deliberately tiny public progress event contract."""

    return f"event: progress\ndata: {json.dumps(event.payload(), ensure_ascii=False, separators=(',', ':'))}\n\n"


def _terminal_progress_event(run: AnalysisRun, sequence: int) -> ProgressEvent:
    if run.status == "failed":
        stage, event_status, summary = "failed", "failed", "Analysis failed safely; final status is available from the report API."
    elif run.status == "limited":
        stage, event_status, summary = "analysis_completed", "limited", "Analysis completed with documented limitations."
    else:
        stage, event_status, summary = "analysis_completed", "completed", "Analysis completed with bounded safeguards."
    timestamp = run.completed_at or run.created_at
    return ProgressEvent(
        sequence=sequence,
        run_id=run.id,
        stage=stage,
        status=event_status,
        summary=summary,
        timestamp=timestamp.isoformat(),
    )


async def _analysis_progress_stream(run_id: str, request: Request):
    """Yield a bounded process-local event tail; cancellation never owns the analysis job."""

    last_sequence = 0
    seconds_since_heartbeat = 0.0
    while True:
        if await request.is_disconnected():
            return

        events = progress_events.after(run_id, last_sequence)
        for event in events:
            last_sequence = event.sequence
            yield _sse_frame(event)
            if event.stage in {"analysis_completed", "failed"}:
                return

        with database.SessionLocal() as stream_session:
            run = stream_session.get(AnalysisRun, run_id)
            if run is None:
                return
            if run.status in TERMINAL_RUN_STATUSES:
                # A process restart may have evicted the in-memory event tail.  The
                # durable run state still lets a subscriber receive one safe terminal
                # signal, never report content.
                yield _sse_frame(_terminal_progress_event(run, last_sequence + 1))
                return

        await asyncio.sleep(SSE_POLL_SECONDS)
        seconds_since_heartbeat += SSE_POLL_SECONDS
        if seconds_since_heartbeat >= SSE_HEARTBEAT_SECONDS:
            seconds_since_heartbeat = 0.0
            yield ": keep-alive\n\n"


@router.post("/analysis-runs/async", response_model=AnalysisRunStarted, status_code=status.HTTP_202_ACCEPTED, tags=["analysis"])
def start_analysis_run(
    payload: AnalysisRequest,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> AnalysisRunStarted:
    """Start the fixed graph independently; subscribe with the returned run ID for safe progress only."""

    try:
        workflow, retriever_model = build_production_workflow()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        run = create_pending_run(session, payload.question, retriever_model=retriever_model)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(execute_pending_run_with_progress, run.id, workflow)
    return AnalysisRunStarted(id=run.id, status="running", events_url=f"/api/v1/analysis-runs/{run.id}/events")


@router.get("/analysis-runs/{run_id}/events", tags=["analysis"])
async def stream_analysis_progress(run_id: str, request: Request, session: SessionDep) -> StreamingResponse:
    """Stream status-only SSE events for one known run; final content stays on the report endpoint."""

    if session.get(AnalysisRun, run_id) is None:
        # This local prototype has no authentication layer.  A future authenticated
        # deployment must apply the same not-found response to unowned run IDs.
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return StreamingResponse(
        _analysis_progress_stream(run_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/analysis-runs/{run_id}", response_model=AnalysisReportRead, tags=["analysis"])
def get_analysis_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    return _analysis_report(session, run_id)


@router.post("/analysis-runs/{run_id}/feedback", response_model=AnalysisFeedbackRead, status_code=status.HTTP_201_CREATED, tags=["analysis"])
def create_analysis_feedback(run_id: str, payload: AnalysisFeedbackCreate, session: SessionDep):
    try:
        return add_feedback(session, run_id, payload.helpful, payload.reason_redacted)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
