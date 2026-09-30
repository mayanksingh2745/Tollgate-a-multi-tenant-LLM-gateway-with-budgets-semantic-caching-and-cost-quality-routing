"""OpenTelemetry Distributed Tracing Initialization and Utilities for Tollgate."""

import logging
import re
from typing import Any, Dict, Optional

from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger("tollgate.observability.tracer")

# Patterns and key names that must NEVER be stored in span attributes
SENSITIVE_KEY_PATTERNS = [
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"prompt", re.IGNORECASE),
    re.compile(r"response[._-]?body", re.IGNORECASE),
    re.compile(r"response[._-]?text", re.IGNORECASE),
    re.compile(r"content", re.IGNORECASE),
    re.compile(r"embedding", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"tool[_-]?args", re.IGNORECASE),
    re.compile(r"arguments", re.IGNORECASE),
]

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"tg_(?:live|test)_[a-zA-Z0-9_\-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9_\-]+"),
]

_tracer_initialized = False


def reset_tracer_provider(provider: Optional[TracerProvider] = None) -> None:
    """Resets the global OpenTelemetry TracerProvider (for test isolation)."""
    global _tracer_initialized
    trace._TRACER_PROVIDER = None
    if hasattr(trace, "_TRACER_PROVIDER_SET_ONCE"):
        trace._TRACER_PROVIDER_SET_ONCE._done = False
    if provider is not None:
        trace.set_tracer_provider(provider)
        _tracer_initialized = True
    else:
        _tracer_initialized = False


def init_tracer(
    service_name: str = "tollgate-api",
    enabled: bool = False,
    endpoint: str = "http://localhost:4318",
    sample_rate: float = 1.0,
    environment: str = "development",
    timeout_seconds: float = 2.0,
) -> trace.Tracer:
    """
    Initializes OpenTelemetry TracerProvider with OTLP HTTP span exporter.
    Configures standard W3C TraceContext propagation and resilient batch export.
    Fails open and safely if exporter is unavailable.
    """
    global _tracer_initialized

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.2.0",
            "deployment.environment": environment,
        }
    )

    if not enabled:
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        _tracer_initialized = True
        return trace.get_tracer(service_name)

    try:
        sampler = ParentBased(root=TraceIdRatioBased(sample_rate))
        provider = TracerProvider(resource=resource, sampler=sampler)

        # OTLP HTTP trace exporter with bounded timeout
        otlp_endpoint = endpoint.rstrip("/")
        if not otlp_endpoint.endswith("/v1/traces"):
            otlp_endpoint = f"{otlp_endpoint}/v1/traces"

        exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            timeout=timeout_seconds,
        )

        # Bounded BatchSpanProcessor to avoid unbounded memory or blocking request thread
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            schedule_delay_millis=500,
            max_export_batch_size=512,
            export_timeout_millis=int(timeout_seconds * 1000),
        )
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        _tracer_initialized = True
        logger.info(
            f"OpenTelemetry tracing initialized for {service_name} (endpoint: {otlp_endpoint}, sample_rate: {sample_rate})"
        )
    except Exception as e:
        logger.warning(
            f"Failed to initialize OpenTelemetry OTLP exporter ({e}); falling back to in-memory tracing."
        )
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)
        _tracer_initialized = True

    return trace.get_tracer(service_name)


class TracerProxy:
    """Proxy tracer that dynamically dispatches to the globally active TracerProvider."""

    def __init__(self, name: str):
        self._name = name

    def start_as_current_span(self, *args, **kwargs):
        return trace.get_tracer(self._name).start_as_current_span(*args, **kwargs)

    def start_span(self, *args, **kwargs):
        return trace.get_tracer(self._name).start_span(*args, **kwargs)

    def __getattr__(self, item: str):
        return getattr(trace.get_tracer(self._name), item)


def get_tracer(name: str = "tollgate") -> trace.Tracer:
    """Returns a dynamic proxy to the currently configured OpenTelemetry tracer."""
    return TracerProxy(name)


def get_current_trace_id() -> Optional[str]:
    """Returns the current 32-character hexadecimal trace ID if active, else None."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return f"{span.get_span_context().trace_id:032x}"
    return None


def get_current_span_id() -> Optional[str]:
    """Returns the current 16-character hexadecimal span ID if active, else None."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        return f"{span.get_span_context().span_id:016x}"
    return None


def get_current_traceparent() -> Optional[str]:
    """Returns the standard W3C traceparent header value if active, else None."""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        ctx = span.get_span_context()
        flags = "01" if ctx.trace_flags.sampled else "00"
        return f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-{flags}"
    return None


def inject_trace_context(carrier: Dict[str, str]) -> None:
    """Injects current W3C trace context into carrier dict (e.g. HTTP headers or message metadata)."""
    propagator = TraceContextTextMapPropagator()
    propagator.inject(carrier)


def extract_trace_context(carrier: Dict[str, str]) -> context.Context:
    """Extracts W3C trace context from carrier dict."""
    propagator = TraceContextTextMapPropagator()
    return propagator.extract(carrier)


def safe_set_attribute(span: trace.Span, key: str, value: Any) -> None:
    """
    Safely sets an attribute on an active span, strictly preventing sensitive data leakage.
    Redacts or ignores passwords, tokens, API keys, prompts, responses, or embeddings.
    """
    if not span or not span.is_recording():
        return

    # 1. Check key name against sensitive patterns
    for pat in SENSITIVE_KEY_PATTERNS:
        if pat.search(key):
            # Block key entirely
            return

    # 2. Check string value against sensitive patterns
    if isinstance(value, str):
        # Bound length
        val_str = value[:1024]
        for pat in SENSITIVE_VALUE_PATTERNS:
            if pat.search(val_str):
                val_str = "[REDACTED]"
                break
        span.set_attribute(key, val_str)
    elif isinstance(value, (int, float, bool)):
        span.set_attribute(key, value)
    elif value is None:
        return
    else:
        # Complex object, safely convert to bounded string
        val_str = str(value)[:512]
        for pat in SENSITIVE_VALUE_PATTERNS:
            if pat.search(val_str):
                val_str = "[REDACTED]"
                break
        span.set_attribute(key, val_str)
