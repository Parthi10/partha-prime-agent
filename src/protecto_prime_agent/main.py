from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .config import get_settings
from .database import init_db
from .logging import attach_correlation_id, build_logger, log_contextual
from .redis_client import check_redis_health
from .schemas import HealthResponse

settings = get_settings()
logger = build_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="Protecto Prime Agent", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next: Any) -> Response:
    correlation_id = attach_correlation_id(request)
    request.state.correlation_id = correlation_id
    logger.info("request_received", extra={"correlation_id": correlation_id})
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/health/live", response_model=HealthResponse)
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/health/ready", response_model=HealthResponse)
async def health_ready() -> HealthResponse | Response:
    try:
        await check_redis_health()
    except Exception as exc:  # pragma: no cover - exercised in tests
        log_contextual("redis_unhealthy", error=str(exc))
        return JSONResponse(status_code=503, content={"status": "degraded"})

    return HealthResponse(status="ok")
