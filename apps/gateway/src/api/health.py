from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from gateway.src.db import check_db_health
from gateway.src.redis import check_redis_health
from pydantic import BaseModel

router = APIRouter()


class ComponentStatus(BaseModel):
    name: str
    status: str  # "healthy" | "unhealthy"
    latency_ms: float = 0.0
    details: str = "OK"


class SystemHealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str = "0.1.0"
    timestamp: str
    services: list[ComponentStatus]


@router.get("/healthz", summary="Simple System Health Check")
async def healthz():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/livez", summary="Liveness Probe")
async def livez():
    return {"status": "alive"}


@router.get("/readyz", summary="Readiness Probe")
async def readyz():
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()

    if not db_ok or not redis_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "database": "ok" if db_ok else "unreachable",
                "redis": "ok" if redis_ok else "unreachable",
            },
        )
    return {"status": "ready", "database": "ok", "redis": "ok"}


@router.get(
    "/api/v1/health", response_model=SystemHealthResponse, summary="Detailed System Health Status"
)
async def detailed_health():
    import time

    # Check Postgres
    t0 = time.perf_counter()
    db_ok = await check_db_health()
    db_latency = (time.perf_counter() - t0) * 1000.0

    # Check Redis
    t0 = time.perf_counter()
    redis_ok = await check_redis_health()
    redis_latency = (time.perf_counter() - t0) * 1000.0

    services = [
        ComponentStatus(
            name="gateway",
            status="healthy",
            latency_ms=0.5,
            details="FastAPI Gateway Engine Operational",
        ),
        ComponentStatus(
            name="postgresql",
            status="healthy" if db_ok else "unhealthy",
            latency_ms=round(db_latency, 2),
            details="PostgreSQL Database Operational" if db_ok else "Connection failed",
        ),
        ComponentStatus(
            name="redis",
            status="healthy" if redis_ok else "unhealthy",
            latency_ms=round(redis_latency, 2),
            details="Redis Cache & Queue Operational" if redis_ok else "Connection failed",
        ),
    ]

    all_healthy = db_ok and redis_ok
    overall_status = "healthy" if all_healthy else "degraded"

    return SystemHealthResponse(
        status=overall_status, timestamp=datetime.now(timezone.utc).isoformat(), services=services
    )
