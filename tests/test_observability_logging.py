import json
import logging

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tollgate_core.observability import (
    StructuredLogFormatter,
    current_project_id,
    current_request_id,
    current_tenant_id,
    get_tracer,
    redact_sensitive_text,
    reset_tracer_provider,
    safe_set_attribute,
)


def test_structured_log_formatter_basic():
    """Verifies that StructuredLogFormatter formats log records as JSON with required fields."""
    formatter = StructuredLogFormatter(service_name="tollgate-api")
    record = logging.LogRecord(
        name="tollgate.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Service initialized",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["level"] == "INFO"
    assert data["service"] == "tollgate-api"
    assert data["logger"] == "tollgate.test"
    assert data["message"] == "Service initialized"
    assert "timestamp" in data


def test_structured_log_correlation_fields():
    """Verifies that request_id, trace_id, and span_id are correlated into logs."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    reset_tracer_provider(provider)
    tracer = get_tracer("test.correlator")

    current_request_id.set("req_test_12345")
    current_tenant_id.set("tenant_abc")
    current_project_id.set("project_xyz")

    formatter = StructuredLogFormatter(service_name="tollgate-api")

    with tracer.start_as_current_span("test.span") as span:
        record = logging.LogRecord(
            name="tollgate.request",
            level=logging.INFO,
            pathname="test.py",
            lineno=25,
            msg="Processing request",
            args=(),
            exc_info=None,
        )
        data = json.loads(formatter.format(record))

        assert data["request_id"] == "req_test_12345"
        assert data["tenant_id"] == "tenant_abc"
        assert data["project_id"] == "project_xyz"
        assert data["trace_id"] == f"{span.get_span_context().trace_id:032x}"
        assert data["span_id"] == f"{span.get_span_context().span_id:016x}"


def test_secret_redaction_in_log_messages():
    """Verifies that API keys, passwords, and authorization tokens are redacted from log messages."""
    raw_message = (
        "User authenticated with Bearer tg_live_secret1234567890abcdef. "
        "Upstream token: sk-live-9876543210. DB config: password=supersecretpass123&ssl=true."
    )
    redacted = redact_sensitive_text(raw_message)

    assert "tg_live_secret1234567890abcdef" not in redacted
    assert "sk-live-9876543210" not in redacted
    assert "supersecretpass123" not in redacted

    assert "Bearer [REDACTED]" in redacted or "tg_[REDACTED]" in redacted
    assert "password=[REDACTED]" in redacted


def test_safe_set_attribute_redaction_and_protection():
    """Verifies that safe_set_attribute blocks sensitive keys and redacts credentials."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
    reset_tracer_provider(provider)
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("test.protection") as span:
        # 1. Sensitive keys must be completely blocked
        safe_set_attribute(span, "api_key", "secret-key")
        safe_set_attribute(span, "authorization", "Bearer xyz")
        safe_set_attribute(span, "user.password", "secretpass")
        safe_set_attribute(span, "prompt", "Translate secret message")
        safe_set_attribute(span, "response_body", "Here is your secret")
        safe_set_attribute(span, "embedding", [0.1, 0.2, 0.3])
        safe_set_attribute(span, "tool_arguments", '{"pin": 1234}')

        assert "api_key" not in span.attributes
        assert "authorization" not in span.attributes
        assert "user.password" not in span.attributes
        assert "prompt" not in span.attributes
        assert "response_body" not in span.attributes
        assert "embedding" not in span.attributes
        assert "tool_arguments" not in span.attributes

        # 2. Sensitive values under allowed keys must be redacted
        safe_set_attribute(span, "tollgate.description", "Using key tg_live_abc123456789")
        assert span.attributes["tollgate.description"] == "[REDACTED]"

        # 3. Safe operational attributes must be preserved
        safe_set_attribute(span, "tollgate.request_id", "req_safe_123")
        safe_set_attribute(span, "http.status_code", 200)
        safe_set_attribute(span, "tollgate.stream", True)
        assert span.attributes["tollgate.request_id"] == "req_safe_123"
        assert span.attributes["http.status_code"] == 200
        assert span.attributes["tollgate.stream"] is True
