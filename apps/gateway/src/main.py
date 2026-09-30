import sys
from pathlib import Path

# Add workspace root to sys.path so imports work seamlessly regardless of launch directory
root_dir = Path(__file__).resolve().parents[3]
core_src = root_dir / "packages" / "core" / "src"
gateway_src = root_dir / "apps" / "gateway"

for p in [str(root_dir), str(core_src), str(gateway_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from gateway.src.api.health import router as health_router
from gateway.src.api.routes.api_keys import router as api_keys_router
from gateway.src.api.routes.chat import router as chat_router
from gateway.src.api.routes.projects import router as projects_router
from gateway.src.api.routes.tenants import router as tenants_router
from gateway.src.api.routes.users import router as users_router
from gateway.src.config import settings
from gateway.src.redis import close_redis_connection
from gateway.src.schemas.chat import OpenAIErrorDetail, OpenAIErrorResponse
from tollgate_core.observability import (
    current_request_id,
    extract_trace_context,
    get_current_trace_id,
    get_current_traceparent,
    get_tracer,
    init_tracer,
    safe_set_attribute,
    setup_logging,
)

tracer = get_tracer("tollgate.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    setup_logging(service_name="tollgate-api", log_level=settings.log_level)
    init_tracer(
        service_name="tollgate-api",
        enabled=settings.otel_enabled,
        endpoint=settings.otel_endpoint,
        sample_rate=settings.otel_trace_sample_rate,
        environment=settings.environment,
        timeout_seconds=settings.otel_export_timeout_seconds,
    )
    print(
        f"[Tollgate Gateway] Starting in {settings.environment} mode (OTel enabled: {settings.otel_enabled})..."
    )
    yield
    # Shutdown sequence
    print("[Tollgate Gateway] Shutting down...")
    await close_redis_connection()


app = FastAPI(
    title="Tollgate LLM Gateway API",
    description="Multi-tenant LLM gateway identity, API key management, and OpenAI-compatible proxy.",
    version="0.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """
    Root HTTP middleware establishing W3C trace propagation, application request_id,
    root 'gateway.request' span, and HTTP response headers.
    """
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:16]}"
    current_request_id.set(request_id)

    headers_dict = dict(request.headers)
    extracted_ctx = extract_trace_context(headers_dict)

    t0 = time.perf_counter()
    with tracer.start_as_current_span("gateway.request", context=extracted_ctx) as span:
        safe_set_attribute(span, "http.request.method", request.method)
        safe_set_attribute(span, "http.route", request.url.path)
        safe_set_attribute(span, "tollgate.request_id", request_id)

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - t0) * 1000.0
            safe_set_attribute(span, "http.response.status_code", response.status_code)
            safe_set_attribute(span, "duration_ms", duration_ms)

            response.headers["X-Request-ID"] = request_id
            trace_id = get_current_trace_id()
            if trace_id:
                response.headers["X-Trace-ID"] = trace_id
            tp = get_current_traceparent()
            if tp:
                response.headers["traceparent"] = tp

            return response
        except Exception:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            safe_set_attribute(span, "http.response.status_code", 500)
            safe_set_attribute(span, "duration_ms", duration_ms)
            raise


from gateway.src.ratelimit import RateLimitExceeded


# Custom validation exception handler to produce OpenAI-compatible errors for 400s
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0] if exc.errors() else {"msg": "Validation failed", "loc": []}
    field = ".".join(str(loc) for loc in first_error.get("loc", []))
    msg = first_error.get("msg", "Invalid parameter")
    error_payload = OpenAIErrorResponse(
        error=OpenAIErrorDetail(
            message=f"{field}: {msg}",
            type="invalid_request_error",
            param=field,
            code="invalid_parameter",
        )
    )
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=error_payload.model_dump())


# RateLimitExceeded exception handler returning standard OpenAI 429
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    headers = exc.result.headers
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers=headers,
        content=OpenAIErrorResponse(
            error=OpenAIErrorDetail(
                message="Rate limit exceeded. Please wait before retrying.",
                type="rate_limit_error",
                code="rate_limit_exceeded",
            )
        ).model_dump(),
    )


from gateway.src.budgets import BudgetExceededError


# BudgetExceededError exception handler returning HTTP 402 Payment Required
@app.exception_handler(BudgetExceededError)
async def budget_exceeded_handler(request: Request, exc: BudgetExceededError):
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content=OpenAIErrorResponse(
            error=OpenAIErrorDetail(
                message=str(exc) or "Budget exceeded. Insufficient spending balance.",
                type="budget_error",
                code="budget_exceeded",
            )
        ).model_dump(),
    )


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from gateway.src.api.routes.auth import router as auth_router
from gateway.src.api.routes.budgets import router as budgets_router
from gateway.src.api.routes.cache import router as cache_router
from gateway.src.api.routes.dashboard import router as dashboard_router
from gateway.src.api.routes.usage import router as usage_router

# Include routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(projects_router)
app.include_router(api_keys_router)
app.include_router(budgets_router)
app.include_router(usage_router)
app.include_router(cache_router)
app.include_router(chat_router)


@app.get("/", summary="Root Endpoint")
async def root():
    return {
        "service": "Tollgate LLM Gateway",
        "phase": "11A - OpenTelemetry, Distributed Tracing & Log Correlation",
        "status": "online",
        "docs_url": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "gateway.src.main:app", host=settings.gateway_host, port=settings.gateway_port, reload=True
    )
