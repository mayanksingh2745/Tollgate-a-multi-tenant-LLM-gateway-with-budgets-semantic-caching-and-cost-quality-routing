"""
Tests for Phase 11B: Prometheus Metrics, Security, Bounded Cardinality & Endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from gateway.src.config import settings
from gateway.src.main import app
from tollgate_core.observability import (
    export_metrics,
    normalize_error_category,
    normalize_model,
    normalize_route,
    record_budget_failure,
    record_budget_release,
    record_budget_reservation,
    record_budget_settlement,
    record_cache_error,
    record_cache_operation,
    record_cache_request,
    record_cache_similarity,
    record_error,
    record_http_request,
    record_provider_call,
    record_provider_fallback,
    record_provider_retry,
    record_provider_timeout,
    record_redis_operation,
    record_router_confidence,
    record_router_decision,
    record_router_duration,
    record_router_error,
    record_router_fallback,
    record_stream_duration,
    record_stream_failure,
    record_stream_request,
    record_stream_ttft,
    record_worker_consumed,
    record_worker_dead_lettered,
    record_worker_failed,
    record_worker_processed,
    record_worker_reclaimed,
    status_code_to_class,
    update_infrastructure_health,
    update_queue_health,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_endpoint_unauthorized(client):
    """Test that /metrics requires authentication when enabled and rejects missing/invalid tokens."""
    orig_auth = settings.metrics_auth_enabled
    orig_token = settings.metrics_token
    try:
        settings.metrics_auth_enabled = True
        settings.metrics_token = "test-secret-token"

        # Missing token
        resp = client.get("/metrics")
        assert resp.status_code == 401
        assert "Unauthorized" in resp.json()["detail"]

        # Invalid token
        resp = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401

        resp = client.get("/metrics", headers={"X-Metrics-Token": "wrong-token"})
        assert resp.status_code == 401
    finally:
        settings.metrics_auth_enabled = orig_auth
        settings.metrics_token = orig_token


def test_metrics_endpoint_authorized(client):
    """Test that /metrics returns valid Prometheus exposition text with valid token."""
    orig_auth = settings.metrics_auth_enabled
    orig_token = settings.metrics_token
    try:
        settings.metrics_auth_enabled = True
        settings.metrics_token = "test-secret-token"

        # Via Bearer Authorization
        resp = client.get("/metrics", headers={"Authorization": "Bearer test-secret-token"})
        assert resp.status_code == 200
        assert "tollgate_http_requests_total" in resp.text
        assert resp.headers["content-type"].startswith("text/plain")

        # Via X-Metrics-Token header
        resp2 = client.get("/metrics", headers={"X-Metrics-Token": "test-secret-token"})
        assert resp2.status_code == 200
    finally:
        settings.metrics_auth_enabled = orig_auth
        settings.metrics_token = orig_token


def test_metrics_no_secrets_or_pii_leaks():
    """Verify that export_metrics does NOT leak API keys, prompts, or sensitive IDs."""
    # Record some realistic operations
    record_http_request("POST", "/v1/chat/completions", 200, 0.045)
    record_provider_call("openai", "gpt-4o", 200, 0.35)

    metrics_text = export_metrics().decode("utf-8")

    # Cardinality & secret verification
    assert "tg_live_" not in metrics_text
    assert "sk-" not in metrics_text
    assert "Bearer " not in metrics_text
    assert "secret" not in metrics_text.lower() or "secret-token" in settings.metrics_token
    assert "prompt_text" not in metrics_text
    assert "tenant_id=" not in metrics_text
    assert "project_id=" not in metrics_text
    assert "request_id=" not in metrics_text
    assert "api_key_id=" not in metrics_text


def test_label_cardinality_sanitizers():
    """Verify string normalization prevents high-cardinality label explosions."""
    # Route normalization
    assert normalize_route("/v1/chat/completions") == "/v1/chat/completions"
    assert normalize_route("/healthz") == "/healthz"
    assert normalize_route("/api/v1/projects/550e8400-e29b-41d4-a716-446655440000") == "/api/v1/projects"
    assert normalize_route("/unknown/random/endpoint") == "other"
    assert normalize_route(None) == "unknown"

    # Model normalization
    assert normalize_model("gpt-4o") == "gpt-4o"
    assert normalize_model("mock-model") == "mock-model"
    assert normalize_model("claude-3-5-sonnet") == "claude-3-5-sonnet"
    assert normalize_model("unregistered-random-custom-fine-tuned-model-xyz") == "custom"
    assert normalize_model(None) == "unspecified"

    # Status class
    assert status_code_to_class(200) == "2xx"
    assert status_code_to_class(201) == "2xx"
    assert status_code_to_class(400) == "4xx"
    assert status_code_to_class(404) == "4xx"
    assert status_code_to_class(500) == "5xx"
    assert status_code_to_class(502) == "5xx"
    assert status_code_to_class(999) == "unknown"

    # Error category
    assert normalize_error_category("rate_limit") == "rate_limit"
    assert normalize_error_category("budget") == "budget"
    assert normalize_error_category("random_unbounded_error_string") == "internal"


def test_provider_reliability_telemetry():
    """Verify provider retry, fallback, timeout, and call metrics recordings."""
    record_provider_call("openai", "gpt-4o", 200, 0.42)
    record_provider_call("anthropic", "claude-3-5-sonnet", 502, 1.25, failure_category="provider_internal")
    record_provider_retry("openai", "gpt-4o")
    record_provider_fallback("openai", "anthropic")
    record_provider_timeout("anthropic", "claude-3-5-sonnet")

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_provider_requests_total{model="gpt-4o",provider="openai",status_class="2xx"}' in metrics_text
    assert 'tollgate_provider_retries_total{model="gpt-4o",provider="openai"}' in metrics_text
    assert 'tollgate_provider_fallbacks_total{provider="openai",target_provider="anthropic"}' in metrics_text
    assert 'tollgate_provider_timeouts_total{model="claude-3-5-sonnet",provider="anthropic"}' in metrics_text


def test_cache_telemetry():
    """Verify exact and semantic cache metrics recordings."""
    record_cache_request("exact", "hit")
    record_cache_request("semantic", "miss")
    record_cache_operation("exact", "lookup", 0.003)
    record_cache_operation("semantic", "store", 0.012)
    record_cache_error("semantic", "embed")
    record_cache_similarity(0.92, "semantic")

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_cache_requests_total{cache_type="exact",result="hit"}' in metrics_text
    assert 'tollgate_cache_requests_total{cache_type="semantic",result="miss"}' in metrics_text
    assert 'tollgate_cache_errors_total{cache_type="semantic",operation="embed"}' in metrics_text
    assert 'tollgate_cache_similarity_score_bucket{cache_type="semantic",le="0.95"}' in metrics_text


def test_router_telemetry():
    """Verify learned model router metrics recordings."""
    record_router_decision("active", "cheap")
    record_router_decision("shadow", "strong")
    record_router_duration("active", "feature_extraction", 0.001)
    record_router_duration("active", "inference", 0.004)
    record_router_confidence("active", 0.88)
    record_router_fallback("active")
    record_router_error("active", "inference_error")

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_router_decisions_total{mode="active",route="cheap"}' in metrics_text
    assert 'tollgate_router_fallbacks_total{mode="active"}' in metrics_text
    assert 'tollgate_router_errors_total{error_type="inference_error",mode="active"}' in metrics_text
    assert 'tollgate_router_confidence_score_bucket{le="0.9",mode="active"}' in metrics_text


def test_budget_telemetry_isolation():
    """Verify budget metrics record operational aggregates and never create tenant-specific series."""
    record_budget_reservation("allowed", duration_seconds=0.002)
    record_budget_reservation("rejected")
    record_budget_failure("insufficient_funds")
    record_budget_settlement("success", duration_seconds=0.003)
    record_budget_release("success", duration_seconds=0.001)

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_budget_reservations_total{status="allowed"}' in metrics_text
    assert 'tollgate_budget_reservations_total{status="rejected"}' in metrics_text
    assert 'tollgate_budget_reservation_failures_total{reason="insufficient_funds"}' in metrics_text
    assert 'tollgate_budget_settlements_total{status="success"}' in metrics_text
    assert 'tollgate_budget_releases_total{status="success"}' in metrics_text


def test_redis_operations_telemetry():
    """Verify Redis operation metrics record component, operation, and status with bounded labels."""
    record_redis_operation("get", "cache", 0.0008, success=True)
    record_redis_operation("set", "ratelimit", 0.0012, success=True)
    record_redis_operation("eval", "budget", 0.0025, success=False)

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_redis_operations_total{component="cache",operation="get",status="success"}' in metrics_text
    assert 'tollgate_redis_errors_total{component="budget",operation="eval"}' in metrics_text


def test_streaming_telemetry():
    """Verify streaming requests, TTFT, duration, disconnects, and failure classifications."""
    record_stream_request("openai", "gpt-4o")
    record_stream_ttft("openai", "gpt-4o", 0.185)
    record_stream_duration("openai", "gpt-4o", 2.45, status="success")
    record_stream_failure("client_disconnect")

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_stream_requests_total{model="gpt-4o",provider="openai"}' in metrics_text
    assert 'tollgate_stream_time_to_first_token_seconds_bucket{le="0.25",model="gpt-4o",provider="openai"}' in metrics_text
    assert 'tollgate_stream_failures_total{failure_class="client_disconnect"}' in metrics_text
    assert 'tollgate_stream_disconnects_total{reason="client_disconnect"}' in metrics_text


def test_worker_and_queue_health_telemetry():
    """Verify worker event counters and queue health gauges."""
    record_worker_consumed("tg:usage:events", count=5)
    record_worker_processed("success", duration_seconds=0.035)
    record_worker_failed("database_error")
    record_worker_reclaimed(count=2)
    record_worker_dead_lettered("validation_error")
    update_queue_health("tg:usage:events", pending_count=42, dead_letter_count=3)
    update_infrastructure_health(redis_ok=True, postgres_ok=True)

    metrics_text = export_metrics().decode("utf-8")
    assert 'tollgate_usage_events_consumed_total{stream="tg:usage:events"}' in metrics_text
    assert 'tollgate_usage_events_processed_total{status="success"}' in metrics_text
    assert 'tollgate_usage_events_failed_total{failure_type="database_error"}' in metrics_text
    assert 'tollgate_usage_events_reclaimed_total' in metrics_text
    assert 'tollgate_usage_queue_pending_messages{stream="tg:usage:events"} 42.0' in metrics_text
    assert 'tollgate_usage_dead_letter_queue_messages{stream="tg:usage:events"} 3.0' in metrics_text
    assert 'tollgate_infrastructure_redis_healthy 1.0' in metrics_text
    assert 'tollgate_infrastructure_postgres_healthy 1.0' in metrics_text


def test_health_endpoints_liveness_and_readiness(client):
    """Verify liveness and readiness probe aliases /health/live and /health/ready."""
    # Liveness
    resp_live = client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json() == {"status": "alive"}

    # Readiness
    resp_ready = client.get("/health/ready")
    # Will be 200 if mocks/services are up, or 503 if DB disconnected in test env
    assert resp_ready.status_code in (200, 503)


def test_telemetry_resilience_to_failures():
    """Verify that malformed or failing telemetry calls never raise unhandled exceptions."""
    # Passing bad types or None shouldn't raise to the caller
    try:
        record_http_request(None, None, 9999, -1.0)
        record_provider_call(None, None, -5, -1.0, None)
        record_cache_operation(None, None, -1.0)
        record_redis_operation(None, None, -1.0, False)
        record_error(None, -1)
    except Exception as e:
        pytest.fail(f"Telemetry helper raised an unhandled exception: {e}")
