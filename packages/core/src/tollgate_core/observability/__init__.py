"""Tollgate Observability: OpenTelemetry Distributed Tracing and Structured Logging."""

from tollgate_core.observability.logging import (
    StructuredLogFormatter,
    current_project_id,
    current_request_id,
    current_tenant_id,
    redact_sensitive_text,
    setup_logging,
)
from tollgate_core.observability.tracer import (
    extract_trace_context,
    get_current_span_id,
    get_current_trace_id,
    get_current_traceparent,
    get_tracer,
    init_tracer,
    inject_trace_context,
    reset_tracer_provider,
    safe_set_attribute,
)

__all__ = [
    "init_tracer",
    "reset_tracer_provider",
    "get_tracer",
    "get_current_trace_id",
    "get_current_span_id",
    "get_current_traceparent",
    "inject_trace_context",
    "extract_trace_context",
    "safe_set_attribute",
    "setup_logging",
    "StructuredLogFormatter",
    "redact_sensitive_text",
    "current_request_id",
    "current_tenant_id",
    "current_project_id",
]
