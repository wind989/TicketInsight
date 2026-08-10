from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import router as api_router
from app.core.logging import configure_logging
from app.core import database


logger = configure_logging()


app = FastAPI(
    title="TicketInsight",
    version="0.1.0",
    description="客服工单智能分析与运营决策平台（P0 开发起点）。",
)

app.include_router(api_router)


@app.middleware("http")
async def audit_request(request: Request, call_next):
    """Record only method, path, status and latency; request bodies, queries and headers are intentionally excluded."""

    request_id = uuid4().hex
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": round((perf_counter() - started_at) * 1000),
                "error_type": type(error).__name__,
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started_at) * 1000),
        },
    )
    return response


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return the minimal process health status for the initial scaffold."""
    return {"status": "ok", "service": "ticketinsight"}


@app.get("/ready", tags=["system"], response_model=None)
async def ready():
    """Report whether the CRUD runtime database is reachable; it does not claim optional analysis services are ready."""

    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_state = "ok"
    except Exception as error:
        logger.warning("readiness_check_failed", extra={"path": "/ready", "status_code": 503, "error_type": type(error).__name__})
        database_state = "unavailable"
    payload = {
        "status": "ready" if database_state == "ok" else "not_ready",
        "scope": "p0_crud_runtime",
        "components": {
            "database": database_state,
            "analysis_runtime": "not_checked",
        },
    }
    if database_state != "ok":
        return JSONResponse(status_code=503, content=payload)
    return payload
