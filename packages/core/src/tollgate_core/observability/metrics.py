"""
Tollgate Observability: Prometheus Metrics & Operational Telemetry.

Production-grade Prometheus counters, gauges, and histograms with bounded cardinality.
High-cardinality values such as tenant_id, project_id, api_key_id, request_id,
trace_id, and prompt text are NEVER used as metric labels.
"""

import logging
from typing import Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,  # noqa: F401
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger("tollgate.observability.metrics")

# ==============================================================================
# Bounded Cardinality Whitelists & Sanitizers
# ==============================================================================

KNOWN_MODELS = {
    "mock-model",
    "mock-fast",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4",
    "gpt-3.5-turbo",
    "claude-3-5-sonnet",
    "claude-3-haiku",
    "claude-3-opus",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "text-embedding-3-small",
    "text-embedding-3-large",
}

KNOWN_ROUTES = {
    "/v1/chat/completions",
    "/api/v1/health",
    "/healthz",
    "/livez",
    "/readyz",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/api/v1/tenants",
    "/api/v1/users",
    "/api/v1/projects",
    "/api/v1/api-keys",
    "/api/v1/budgets",
    "/api/v1/usage",
    "/api/v1/dashboard",
    "/api/v1/cache",
}

KNOWN_ERROR_CATEGORIES = {
    "authentication",
    "authorization",
    "validation",
    "rate_limit",
    "budget",
    "cache",
    "provider_timeout",
    "provider_rate_limit",
    "provider_auth",
    "provider_not_found",
    "provider_content",
    "provider_internal",
    "internal",
}


def normalize_route(path: Optional[str]) -> str:
    """Safely normalizes HTTP route to prevent unbounded label cardinality."""
    if not path:
        return "unknown"
    if path in KNOWN_ROUTES:
        return path
    for prefix in [
        "/v1/chat/completions",
        "/api/v1/health",
        "/api/v1/dashboard",
        "/api/v1/tenants",
        "/api/v1/users",
        "/api/v1/projects",
        "/api/v1/api-keys",
        "/api/v1/budgets",
        "/api/v1/usage",
        "/api/v1/cache",
    ]:
        if path.startswith(prefix):
            return prefix
    return "other"


def normalize_model(model: Optional[str]) -> str:
    """Normalizes model identifier to prevent unbounded label cardinality from user strings."""
    if not model:
        return "unspecified"
    model_lower = model.lower().strip()
    if model_lower in KNOWN_MODELS:
        return model_lower
    # Prefix matches for versioned provider models
    for known in KNOWN_MODELS:
        if model_lower.startswith(known):
            return known
    return "custom"


def status_code_to_class(status_code: int) -> str:
    """Converts HTTP status code into bounded class: 2xx, 4xx, 5xx, etc."""
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "unknown"


def normalize_error_category(category: Optional[str]) -> str:
    """Ensures error category belongs to bounded enumerated set."""
    if not category:
        return "internal"
    cat_lower = str(category).lower().strip()
    if cat_lower in KNOWN_ERROR_CATEGORIES:
        return cat_lower
    return "internal"


# ==============================================================================
# 1. Gateway HTTP Metrics (Histograms for p50, p95, p99)
# ==============================================================================

HTTP_REQUESTS_TOTAL = Counter(
    "tollgate_http_requests_total",
    "Total HTTP requests handled by the gateway",
    ["method", "route", "status_class"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "tollgate_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route", "status_class"],
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        15.0,
        30.0,
        60.0,
    ),
)

# ==============================================================================
# 2. Provider Metrics (Reliability, Latency, Failovers)
# ==============================================================================

PROVIDER_REQUESTS_TOTAL = Counter(
    "tollgate_provider_requests_total",
    "Total requests dispatched to upstream LLM providers",
    ["provider", "model", "status_class"],
)

PROVIDER_ERRORS_TOTAL = Counter(
    "tollgate_provider_errors_total",
    "Total upstream LLM provider failures",
    ["provider", "model", "status_class", "failure_category"],
)

PROVIDER_RETRIES_TOTAL = Counter(
    "tollgate_provider_retries_total",
    "Total upstream provider retry attempts",
    ["provider", "model"],
)

PROVIDER_FALLBACKS_TOTAL = Counter(
    "tollgate_provider_fallbacks_total",
    "Total provider fallback events triggered",
    ["provider", "target_provider"],
)

PROVIDER_TIMEOUTS_TOTAL = Counter(
    "tollgate_provider_timeouts_total",
    "Total upstream provider requests exceeding deadline or timeout",
    ["provider", "model"],
)

PROVIDER_REQUEST_DURATION_SECONDS = Histogram(
    "tollgate_provider_request_duration_seconds",
    "Upstream provider call latency in seconds",
    ["provider", "model", "status_class"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0),
)

# ==============================================================================
# 3. Cache Metrics (Exact & Semantic)
# ==============================================================================

CACHE_REQUESTS_TOTAL = Counter(
    "tollgate_cache_requests_total",
    "Total exact and semantic cache lookups",
    ["cache_type", "result"],  # cache_type: exact|semantic, result: hit|miss|bypass
)

CACHE_ERRORS_TOTAL = Counter(
    "tollgate_cache_errors_total",
    "Total cache errors encountered",
    ["cache_type", "operation"],  # operation: lookup|store|embed
)

CACHE_OPERATION_DURATION_SECONDS = Histogram(
    "tollgate_cache_operation_duration_seconds",
    "Cache lookup and store duration in seconds",
    ["cache_type", "operation"],
    buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

CACHE_SIMILARITY_SCORE = Histogram(
    "tollgate_cache_similarity_score",
    "Semantic cache cosine similarity scores for evaluated candidates",
    ["cache_type"],
    buckets=(0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.98, 1.0),
)

# ==============================================================================
# 4. Learned Model Router Metrics
# ==============================================================================

ROUTER_DECISIONS_TOTAL = Counter(
    "tollgate_router_decisions_total",
    "Total routing decisions made by the learned model router",
    ["mode", "route"],  # mode: disabled|shadow|active, route: cheap|strong|passthrough
)

ROUTER_ERRORS_TOTAL = Counter(
    "tollgate_router_errors_total",
    "Total router errors during feature extraction or model inference",
    ["mode", "error_type"],
)

ROUTER_FALLBACKS_TOTAL = Counter(
    "tollgate_router_fallbacks_total",
    "Total router fallback activations due to error, low confidence, or missing model",
    ["mode"],
)

ROUTER_DECISION_DURATION_SECONDS = Histogram(
    "tollgate_router_decision_duration_seconds",
    "Router latency in seconds",
    ["mode", "stage"],  # stage: feature_extraction|inference
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1),
)

ROUTER_CONFIDENCE_SCORE = Histogram(
    "tollgate_router_confidence_score",
    "Router prediction confidence score distribution",
    ["mode"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# ==============================================================================
# 5. Budget Metrics (Operational Aggregations - Never Per-Tenant)
# ==============================================================================

BUDGET_RESERVATIONS_TOTAL = Counter(
    "tollgate_budget_reservations_total",
    "Total atomic budget reservation attempts",
    ["status"],  # allowed|rejected
)

BUDGET_RESERVATION_FAILURES_TOTAL = Counter(
    "tollgate_budget_reservation_failures_total",
    "Total budget reservation failures or rejections",
    ["reason"],  # insufficient_funds|redis_error|timeout
)

BUDGET_SETTLEMENTS_TOTAL = Counter(
    "tollgate_budget_settlements_total",
    "Total budget settlement operations",
    ["status"],  # success|error
)

BUDGET_RELEASES_TOTAL = Counter(
    "tollgate_budget_releases_total",
    "Total budget release operations on cancellation or error",
    ["status"],  # success|error
)

BUDGET_OPERATION_DURATION_SECONDS = Histogram(
    "tollgate_budget_operation_duration_seconds",
    "Duration of atomic budget Redis operations in seconds",
    ["operation"],  # reserve|settle|release
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

# ==============================================================================
# 6. Redis Metrics (Bounded Operations, Never Key/Tenant)
# ==============================================================================

REDIS_OPERATIONS_TOTAL = Counter(
    "tollgate_redis_operations_total",
    "Total Redis commands executed by component",
    ["operation", "component", "status"],  # status: success|error
)

REDIS_OPERATION_DURATION_SECONDS = Histogram(
    "tollgate_redis_operation_duration_seconds",
    "Redis operation latency in seconds",
    ["operation", "component"],
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

REDIS_ERRORS_TOTAL = Counter(
    "tollgate_redis_errors_total",
    "Total Redis command failures",
    ["operation", "component"],
)

# ==============================================================================
# 7. Usage Worker & Queue Health Metrics
# ==============================================================================

USAGE_EVENTS_CONSUMED_TOTAL = Counter(
    "tollgate_usage_events_consumed_total",
    "Total usage events read from the Redis stream",
    ["stream"],
)

USAGE_EVENTS_PROCESSED_TOTAL = Counter(
    "tollgate_usage_events_processed_total",
    "Total usage events persisted to PostgreSQL and acknowledged",
    ["status"],  # success|failure
)

USAGE_EVENTS_FAILED_TOTAL = Counter(
    "tollgate_usage_events_failed_total",
    "Total usage events that failed persistence or validation",
    ["failure_type"],  # validation_error|database_error|unknown
)

USAGE_EVENTS_RECLAIMED_TOTAL = Counter(
    "tollgate_usage_events_reclaimed_total",
    "Total stale pending usage events reclaimed from stalled worker instances",
)

USAGE_EVENTS_DEAD_LETTERED_TOTAL = Counter(
    "tollgate_usage_events_dead_lettered_total",
    "Total usage events moved to the dead-letter stream",
    ["reason"],
)

USAGE_PROCESSING_DURATION_SECONDS = Histogram(
    "tollgate_usage_processing_duration_seconds",
    "Worker event batch/item processing duration in seconds",
    ["status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

USAGE_QUEUE_PENDING_MESSAGES = Gauge(
    "tollgate_usage_queue_pending_messages",
    "Current pending unacknowledged message count in consumer group",
    ["stream"],
)

USAGE_DEAD_LETTER_QUEUE_MESSAGES = Gauge(
    "tollgate_usage_dead_letter_queue_messages",
    "Current message count in the dead-letter stream",
    ["stream"],
)

# ==============================================================================
# 8. Streaming Metrics (TTFT, Duration, Disconnects)
# ==============================================================================

STREAM_REQUESTS_TOTAL = Counter(
    "tollgate_stream_requests_total",
    "Total SSE streaming requests received",
    ["provider", "model"],
)

STREAM_DURATION_SECONDS = Histogram(
    "tollgate_stream_duration_seconds",
    "Full stream duration from initial request to connection completion",
    ["provider", "model", "status"],  # status: success|client_disconnect|error
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)

STREAM_TIME_TO_FIRST_TOKEN_SECONDS = Histogram(
    "tollgate_stream_time_to_first_token_seconds",
    "Time to first token (TTFT) for streaming responses",
    ["provider", "model"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0),
)

STREAM_DISCONNECTS_TOTAL = Counter(
    "tollgate_stream_disconnects_total",
    "Total streaming connections closed early by the client",
    ["reason"],
)

STREAM_FAILURES_TOTAL = Counter(
    "tollgate_stream_failures_total",
    "Total stream failures grouped by failure classification",
    ["failure_class"],  # client_disconnect|provider_failure|timeout|gateway_failure
)

# ==============================================================================
# 9. Error Metrics (Normalized Categories)
# ==============================================================================

ERRORS_TOTAL = Counter(
    "tollgate_errors_total",
    "Total errors across the gateway by normalized category and HTTP status code",
    ["category", "status_code"],
)

# ==============================================================================
# 10. Infrastructure Health Metrics
# ==============================================================================

INFRASTRUCTURE_REDIS_HEALTHY = Gauge(
    "tollgate_infrastructure_redis_healthy",
    "Redis connectivity status (1 = healthy, 0 = unhealthy)",
)

INFRASTRUCTURE_POSTGRES_HEALTHY = Gauge(
    "tollgate_infrastructure_postgres_healthy",
    "PostgreSQL connectivity status (1 = healthy, 0 = unhealthy)",
)

INFRASTRUCTURE_POSTGRES_POOL_SIZE = Gauge(
    "tollgate_infrastructure_postgres_pool_size",
    "Current PostgreSQL connection pool total capacity",
)

INFRASTRUCTURE_POSTGRES_POOL_CHECKEDOUT = Gauge(
    "tollgate_infrastructure_postgres_pool_checkedout",
    "Current PostgreSQL connections checked out from the pool",
)


# ==============================================================================
# 11. Circuit Breaker Metrics
# ==============================================================================

CIRCUIT_TRANSITIONS_TOTAL = Counter(
    "tollgate_circuit_transitions_total",
    "Total circuit breaker state transitions",
    ["provider", "model", "from_state", "to_state"],
)

CIRCUIT_REJECTIONS_TOTAL = Counter(
    "tollgate_circuit_rejections_total",
    "Total requests rejected because provider circuit was OPEN",
    ["provider", "model"],
)

CIRCUIT_HALF_OPEN_PROBES_TOTAL = Counter(
    "tollgate_circuit_half_open_probes_total",
    "Total half-open probe requests permitted",
    ["provider", "model", "result"],  # result: success|failure
)

CIRCUIT_STATE = Gauge(
    "tollgate_circuit_state",
    "Current circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["provider", "model"],
)

# ==============================================================================
# 12. High Availability & Resilience Metrics (Phase 16)
# ==============================================================================

RECOVERY_EVENTS_TOTAL = Counter(
    "tollgate_recovery_events_total",
    "Total automated or manual recovery events executed",
    ["component", "status"],  # component: postgres|redis|worker|api; status: success|failure
)

FAILOVER_TOTAL = Counter(
    "tollgate_failover_total",
    "Total automated failover events between replicas or providers",
    ["target_type", "status"],  # target_type: api_replica|provider; status: success|failure
)

BACKUP_OPERATIONS_TOTAL = Counter(
    "tollgate_backup_operations_total",
    "Total database backup operations executed",
    ["operation", "status"],  # operation: backup|restore|verify; status: success|failure
)


# ==============================================================================
# Helper Functions (Fail-Safe: Never crash caller on telemetry errors)
# ==============================================================================


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    """Records an HTTP request and its duration with bounded labels."""
    try:
        route = normalize_route(path)
        status_class = status_code_to_class(status_code)
        HTTP_REQUESTS_TOTAL.labels(
            method=method.upper(), route=route, status_class=status_class
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method.upper(), route=route, status_class=status_class
        ).observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record HTTP metrics: {e}")


def record_provider_call(
    provider: str,
    model: str,
    status_code: int,
    duration_seconds: float,
    failure_category: Optional[str] = None,
) -> None:
    """Records an upstream provider attempt."""
    try:
        norm_model = normalize_model(model)
        status_class = status_code_to_class(status_code)
        PROVIDER_REQUESTS_TOTAL.labels(
            provider=provider, model=norm_model, status_class=status_class
        ).inc()
        PROVIDER_REQUEST_DURATION_SECONDS.labels(
            provider=provider, model=norm_model, status_class=status_class
        ).observe(duration_seconds)
        if status_class in ("4xx", "5xx") or failure_category:
            cat = normalize_error_category(failure_category)
            PROVIDER_ERRORS_TOTAL.labels(
                provider=provider,
                model=norm_model,
                status_class=status_class,
                failure_category=cat,
            ).inc()
    except Exception as e:
        logger.debug(f"Failed to record provider metrics: {e}")


def record_provider_retry(provider: str, model: str) -> None:
    """Records a provider retry attempt."""
    try:
        norm_model = normalize_model(model)
        PROVIDER_RETRIES_TOTAL.labels(provider=provider, model=norm_model).inc()
    except Exception as e:
        logger.debug(f"Failed to record provider retry: {e}")


def record_provider_fallback(source_provider: str, target_provider: str) -> None:
    """Records a provider failover/fallback."""
    try:
        PROVIDER_FALLBACKS_TOTAL.labels(
            provider=source_provider, target_provider=target_provider
        ).inc()
    except Exception as e:
        logger.debug(f"Failed to record provider fallback: {e}")


def record_provider_timeout(provider: str, model: str) -> None:
    """Records a provider timeout event."""
    try:
        norm_model = normalize_model(model)
        PROVIDER_TIMEOUTS_TOTAL.labels(provider=provider, model=norm_model).inc()
    except Exception as e:
        logger.debug(f"Failed to record provider timeout: {e}")


def record_cache_request(cache_type: str, result: str) -> None:
    """Records exact or semantic cache hit/miss/bypass."""
    try:
        CACHE_REQUESTS_TOTAL.labels(cache_type=cache_type, result=result.lower()).inc()
    except Exception as e:
        logger.debug(f"Failed to record cache request: {e}")


def record_cache_operation(cache_type: str, operation: str, duration_seconds: float) -> None:
    """Records cache lookup or store duration."""
    try:
        CACHE_OPERATION_DURATION_SECONDS.labels(cache_type=cache_type, operation=operation).observe(
            duration_seconds
        )
    except Exception as e:
        logger.debug(f"Failed to record cache operation: {e}")


def record_cache_error(cache_type: str, operation: str) -> None:
    """Records cache error."""
    try:
        CACHE_ERRORS_TOTAL.labels(cache_type=cache_type, operation=operation).inc()
    except Exception as e:
        logger.debug(f"Failed to record cache error: {e}")


def record_cache_similarity(score: float, cache_type: str = "semantic") -> None:
    """Records semantic cache cosine similarity score."""
    try:
        CACHE_SIMILARITY_SCORE.labels(cache_type=cache_type).observe(score)
    except Exception as e:
        logger.debug(f"Failed to record cache similarity: {e}")


def record_router_decision(mode: str, route: str) -> None:
    """Records router decision (cheap/strong/passthrough)."""
    try:
        ROUTER_DECISIONS_TOTAL.labels(mode=mode, route=route).inc()
    except Exception as e:
        logger.debug(f"Failed to record router decision: {e}")


def record_router_duration(mode: str, stage: str, duration_seconds: float) -> None:
    """Records router feature extraction or inference duration."""
    try:
        ROUTER_DECISION_DURATION_SECONDS.labels(mode=mode, stage=stage).observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record router duration: {e}")


def record_router_fallback(mode: str) -> None:
    """Records router fallback to baseline model."""
    try:
        ROUTER_FALLBACKS_TOTAL.labels(mode=mode).inc()
    except Exception as e:
        logger.debug(f"Failed to record router fallback: {e}")


def record_router_error(mode: str, error_type: str) -> None:
    """Records router error."""
    try:
        ROUTER_ERRORS_TOTAL.labels(mode=mode, error_type=error_type).inc()
    except Exception as e:
        logger.debug(f"Failed to record router error: {e}")


def record_router_confidence(mode: str, confidence: float) -> None:
    """Records router confidence score."""
    try:
        ROUTER_CONFIDENCE_SCORE.labels(mode=mode).observe(confidence)
    except Exception as e:
        logger.debug(f"Failed to record router confidence: {e}")


def record_budget_reservation(status: str, duration_seconds: Optional[float] = None) -> None:
    """Records budget reservation attempt."""
    try:
        BUDGET_RESERVATIONS_TOTAL.labels(status=status).inc()
        if duration_seconds is not None:
            BUDGET_OPERATION_DURATION_SECONDS.labels(operation="reserve").observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record budget reservation: {e}")


def record_budget_failure(reason: str) -> None:
    """Records budget reservation rejection or failure."""
    try:
        BUDGET_RESERVATION_FAILURES_TOTAL.labels(reason=reason).inc()
    except Exception as e:
        logger.debug(f"Failed to record budget failure: {e}")


def record_budget_settlement(status: str, duration_seconds: Optional[float] = None) -> None:
    """Records budget settlement operation."""
    try:
        BUDGET_SETTLEMENTS_TOTAL.labels(status=status).inc()
        if duration_seconds is not None:
            BUDGET_OPERATION_DURATION_SECONDS.labels(operation="settle").observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record budget settlement: {e}")


def record_budget_release(status: str, duration_seconds: Optional[float] = None) -> None:
    """Records budget release operation."""
    try:
        BUDGET_RELEASES_TOTAL.labels(status=status).inc()
        if duration_seconds is not None:
            BUDGET_OPERATION_DURATION_SECONDS.labels(operation="release").observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record budget release: {e}")


def record_redis_operation(
    operation: str, component: str, duration_seconds: float, success: bool = True
) -> None:
    """Records a Redis command execution with bounded labels."""
    try:
        status_str = "success" if success else "error"
        REDIS_OPERATIONS_TOTAL.labels(
            operation=operation, component=component, status=status_str
        ).inc()
        REDIS_OPERATION_DURATION_SECONDS.labels(operation=operation, component=component).observe(
            duration_seconds
        )
        if not success:
            REDIS_ERRORS_TOTAL.labels(operation=operation, component=component).inc()
    except Exception as e:
        logger.debug(f"Failed to record Redis metrics: {e}")


def record_stream_request(provider: str, model: str) -> None:
    """Records start of an SSE streaming completion request."""
    try:
        norm_model = normalize_model(model)
        STREAM_REQUESTS_TOTAL.labels(provider=provider, model=norm_model).inc()
    except Exception as e:
        logger.debug(f"Failed to record stream request: {e}")


def record_stream_ttft(provider: str, model: str, ttft_seconds: float) -> None:
    """Records time to first token for streaming responses."""
    try:
        norm_model = normalize_model(model)
        STREAM_TIME_TO_FIRST_TOKEN_SECONDS.labels(provider=provider, model=norm_model).observe(
            ttft_seconds
        )
    except Exception as e:
        logger.debug(f"Failed to record stream TTFT: {e}")


def record_stream_duration(provider: str, model: str, duration_seconds: float, status: str) -> None:
    """Records total stream duration."""
    try:
        norm_model = normalize_model(model)
        STREAM_DURATION_SECONDS.labels(provider=provider, model=norm_model, status=status).observe(
            duration_seconds
        )
    except Exception as e:
        logger.debug(f"Failed to record stream duration: {e}")


def record_stream_failure(failure_class: str) -> None:
    """Records a stream failure or disconnect."""
    try:
        STREAM_FAILURES_TOTAL.labels(failure_class=failure_class).inc()
        if "disconnect" in failure_class:
            STREAM_DISCONNECTS_TOTAL.labels(reason=failure_class).inc()
    except Exception as e:
        logger.debug(f"Failed to record stream failure: {e}")


def record_stream_disconnect(reason: str = "client_disconnect") -> None:
    """Records a client disconnect during streaming."""
    try:
        STREAM_DISCONNECTS_TOTAL.labels(reason=reason).inc()
        STREAM_FAILURES_TOTAL.labels(failure_class=reason).inc()
    except Exception as e:
        logger.debug(f"Failed to record stream disconnect: {e}")


def record_error(category: str, status_code: int) -> None:
    """Records an error categorized by normalized category and HTTP status code."""
    try:
        cat = normalize_error_category(category)
        ERRORS_TOTAL.labels(category=cat, status_code=str(status_code)).inc()
    except Exception as e:
        logger.debug(f"Failed to record error metric: {e}")


def record_worker_consumed(stream_name: str, count: int = 1) -> None:
    """Records usage events read from stream."""
    try:
        USAGE_EVENTS_CONSUMED_TOTAL.labels(stream=stream_name).inc(count)
    except Exception as e:
        logger.debug(f"Failed to record worker consumed: {e}")


def record_worker_processed(status: str, duration_seconds: float) -> None:
    """Records usage event processing outcome and latency."""
    try:
        USAGE_EVENTS_PROCESSED_TOTAL.labels(status=status).inc()
        USAGE_PROCESSING_DURATION_SECONDS.labels(status=status).observe(duration_seconds)
    except Exception as e:
        logger.debug(f"Failed to record worker processed: {e}")


def record_worker_failed(failure_type: str) -> None:
    """Records usage event failure."""
    try:
        USAGE_EVENTS_FAILED_TOTAL.labels(failure_type=failure_type).inc()
    except Exception as e:
        logger.debug(f"Failed to record worker failed: {e}")


def record_worker_reclaimed(count: int = 1) -> None:
    """Records reclaimed stale messages."""
    try:
        USAGE_EVENTS_RECLAIMED_TOTAL.inc(count)
    except Exception as e:
        logger.debug(f"Failed to record worker reclaimed: {e}")


def record_worker_dead_lettered(reason: str) -> None:
    """Records unprocessable message moved to dead-letter stream."""
    try:
        USAGE_EVENTS_DEAD_LETTERED_TOTAL.labels(reason=reason[:64]).inc()
    except Exception as e:
        logger.debug(f"Failed to record dead letter event: {e}")


def update_queue_health(stream: str, pending_count: int, dead_letter_count: int) -> None:
    """Updates gauges for pending consumer group messages and dead-letter count."""
    try:
        USAGE_QUEUE_PENDING_MESSAGES.labels(stream=stream).set(pending_count)
        USAGE_DEAD_LETTER_QUEUE_MESSAGES.labels(stream=stream).set(dead_letter_count)
    except Exception as e:
        logger.debug(f"Failed to update queue health gauges: {e}")


def update_infrastructure_health(redis_ok: bool, postgres_ok: bool) -> None:
    """Updates infrastructure health gauges."""
    try:
        INFRASTRUCTURE_REDIS_HEALTHY.set(1.0 if redis_ok else 0.0)
        INFRASTRUCTURE_POSTGRES_HEALTHY.set(1.0 if postgres_ok else 0.0)
    except Exception as e:
        logger.debug(f"Failed to update infrastructure health: {e}")


def record_circuit_transition(provider: str, model: str, from_state: str, to_state: str) -> None:
    """Records a circuit breaker state transition."""
    try:
        norm_model = normalize_model(model)
        CIRCUIT_TRANSITIONS_TOTAL.labels(
            provider=provider, model=norm_model, from_state=from_state, to_state=to_state
        ).inc()
        state_val = {"closed": 0.0, "open": 1.0, "half_open": 2.0}.get(to_state, 0.0)
        CIRCUIT_STATE.labels(provider=provider, model=norm_model).set(state_val)
    except Exception as e:
        logger.debug(f"Failed to record circuit transition: {e}")


def record_circuit_rejection(provider: str, model: str) -> None:
    """Records a request rejected because the circuit was OPEN."""
    try:
        norm_model = normalize_model(model)
        CIRCUIT_REJECTIONS_TOTAL.labels(provider=provider, model=norm_model).inc()
    except Exception as e:
        logger.debug(f"Failed to record circuit rejection: {e}")


def record_circuit_half_open_probe(provider: str, model: str, result: str) -> None:
    """Records a half-open probe result (success or failure)."""
    try:
        norm_model = normalize_model(model)
        CIRCUIT_HALF_OPEN_PROBES_TOTAL.labels(
            provider=provider, model=norm_model, result=result
        ).inc()
    except Exception as e:
        logger.debug(f"Failed to record circuit probe: {e}")


def record_recovery_event(component: str, status: str) -> None:
    """Records an infrastructure recovery event with bounded labels."""
    try:
        RECOVERY_EVENTS_TOTAL.labels(
            component=str(component).lower(), status=str(status).lower()
        ).inc()
    except Exception as e:
        logger.debug(f"Failed to record recovery event metric: {e}")


def record_failover_event(target_type: str, status: str) -> None:
    """Records a failover event with bounded labels."""
    try:
        FAILOVER_TOTAL.labels(
            target_type=str(target_type).lower(), status=str(status).lower()
        ).inc()
    except Exception as e:
        logger.debug(f"Failed to record failover event metric: {e}")


def record_backup_operation(operation: str, status: str) -> None:
    """Records a backup or restore operation with bounded labels."""
    try:
        BACKUP_OPERATIONS_TOTAL.labels(
            operation=str(operation).lower(), status=str(status).lower()
        ).inc()
    except Exception as e:
        logger.debug(f"Failed to record backup operation metric: {e}")


def export_metrics() -> bytes:
    """Serializes all Prometheus metrics into the standard Prometheus exposition format."""
    return generate_latest(REGISTRY)
