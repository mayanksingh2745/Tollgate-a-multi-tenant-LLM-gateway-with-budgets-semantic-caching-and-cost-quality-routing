from unittest.mock import MagicMock, patch

import pytest
from gateway.src.main import app
from httpx import ASGITransport, AsyncClient
from tollgate_core.observability import (
    get_tracer,
    init_tracer,
    record_error,
    record_http_request,
    safe_set_attribute,
)


@pytest.mark.asyncio
async def test_opentelemetry_collector_failure_isolation():
    """
    Verifies that when OpenTelemetry collector is unreachable or throws network errors,
    the gateway's tracing helpers swallow errors silently without breaking client requests.
    """
    # Initialize tracer pointing to non-existent endpoint
    init_tracer(
        service_name="tollgate-api-resilience-test",
        enabled=True,
        endpoint="http://127.0.0.1:9999",  # unreachable
        sample_rate=1.0,
        timeout_seconds=0.1,
    )

    tracer = get_tracer("tollgate.resilience")

    # Creating spans and recording attributes must never raise exceptions
    try:
        with tracer.start_as_current_span("test.resilience.span") as span:
            safe_set_attribute(span, "test.attr", "value")
            safe_set_attribute(span, "test.num", 12345)
            # Safe attribute helper with broken span object
            broken_span = MagicMock()
            broken_span.set_attribute.side_effect = RuntimeError("OTel internal buffer error")
            safe_set_attribute(broken_span, "broken", "value")
    except Exception as e:
        pytest.fail(f"Tracing error leaked into application execution: {e}")


@pytest.mark.asyncio
async def test_prometheus_metrics_failure_isolation():
    """
    Verifies that if Prometheus metric recording encounters an unexpected failure,
    it fails safe and does not bubble up to the HTTP caller.
    """
    mock_metric = MagicMock()
    mock_metric.labels.side_effect = RuntimeError("Prometheus storage engine panic")
    with patch("tollgate_core.observability.metrics.HTTP_REQUESTS_TOTAL", mock_metric):
        # Must not raise exception even if internal metric object raises RuntimeError
        try:
            record_http_request(
                method="POST",
                path="/v1/chat/completions",
                status_code=200,
                duration_seconds=0.05,
            )
            record_error(category="test_category", status_code=500)
        except Exception as e:
            pytest.fail(f"Metric recording error leaked into application execution: {e}")


@pytest.mark.asyncio
async def test_http_request_succeeds_despite_observability_backend_crash():
    """
    Simulates complete observability backend crash while handling a real HTTP request
    through the FastAPI application: request must return HTTP 200 without degradation.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Patch tracer and metrics to simulate background crash
        with (
            patch(
                "tollgate_core.observability.record_http_request",
                side_effect=Exception("Prometheus unavailable"),
            ),
            patch(
                "tollgate_core.observability.extract_trace_context",
                side_effect=Exception("Trace context corrupted"),
            ),
        ):

            res = await client.get("/healthz")
            # Must still succeed cleanly
            assert res.status_code == 200
            assert res.json()["status"] == "ok"
