import pytest
from httpx import AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tollgate_core.observability import reset_tracer_provider, safe_set_attribute

from tests.security.security_fixtures import create_security_tenant_fixture


@pytest.mark.asyncio
async def test_unhandled_exception_sanitization(async_client: AsyncClient):
    """An unhandled internal exception must return a safe 500 error envelope without stack traces."""
    _ = await create_security_tenant_fixture(async_client, "err1")

    # Call a dummy or faulty endpoint
    from fastapi import APIRouter
    from gateway.src.main import app

    dummy_router = APIRouter()

    @dummy_router.get("/api/v1/test-faulty-crash")
    async def crash_endpoint():
        raise RuntimeError("Database connection string postgresql://user:secret_pass@10.0.0.1:5432/db failed")

    app.include_router(dummy_router)

    res = await async_client.get("/api/v1/test-faulty-crash")
    assert res.status_code == 500
    data = res.json()
    assert "error" in data
    err = data["error"]
    assert err["type"] == "internal_server_error"
    assert err["message"] == "An internal server error occurred."
    # Secrets and stack trace must NOT appear in response body
    body_str = str(data)
    assert "secret_pass" not in body_str
    assert "Traceback" not in body_str
    assert "10.0.0.1" not in body_str


@pytest.mark.asyncio
async def test_opentelemetry_trace_sanitization(async_client: AsyncClient):
    """Synthetic sensitive request trace must NOT contain raw keys, passwords, or prompts."""
    # Setup in-memory span exporter to capture traces
    memory_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory_exporter))
    reset_tracer_provider(provider)

    fixture = await create_security_tenant_fixture(async_client, "otel1")

    sensitive_prompt = "TOP_SECRET_PASSWORD_12345"
    res = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {fixture.owner_api_key}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": sensitive_prompt}],
        },
    )
    assert res.status_code == 200

    spans = memory_exporter.get_finished_spans()
    assert len(spans) > 0

    for span in spans:
        attrs = span.attributes or {}
        for k, v in attrs.items():
            val_str = str(v)
            # Sensitive prompt text must not be in span attributes
            assert sensitive_prompt not in val_str, f"Prompt leaked in span attribute '{k}': {val_str}"
            # Raw API key must not be in span attributes
            assert fixture.owner_api_key not in val_str, f"Raw API key leaked in span attribute '{k}'"
            # Forbidden key names
            assert "prompt" not in k.lower(), f"Forbidden attribute key: {k}"
            assert "authorization" not in k.lower(), f"Forbidden attribute key: {k}"
            assert "password" not in k.lower(), f"Forbidden attribute key: {k}"

    reset_tracer_provider(None)


@pytest.mark.asyncio
async def test_safe_set_attribute_redacts_sensitive_patterns():
    """Unit test for safe_set_attribute: keys matching sensitive patterns are blocked or redacted."""
    memory_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory_exporter))
    tracer = provider.get_tracer("test.tracer")

    with tracer.start_as_current_span("test.span") as span:
        # Sensitive key names: blocked entirely
        safe_set_attribute(span, "api_key", "secret123")
        safe_set_attribute(span, "authorization", "Bearer xyz")
        safe_set_attribute(span, "user.password", "pass123")
        safe_set_attribute(span, "prompt", "what is my secret")
        safe_set_attribute(span, "embedding", [0.1, 0.2])

        # Sensitive value regexes: redacted
        safe_set_attribute(span, "custom_tag", "My key is tg_live_abcdef1234567890abcdef")
        safe_set_attribute(span, "safe_tag", "regular_value")

    finished = memory_exporter.get_finished_spans()
    assert len(finished) == 1
    attrs = finished[0].attributes or {}

    assert "api_key" not in attrs
    assert "authorization" not in attrs
    assert "user.password" not in attrs
    assert "prompt" not in attrs
    assert "embedding" not in attrs

    assert attrs.get("safe_tag") == "regular_value"
    assert attrs.get("custom_tag") == "[REDACTED]"
