"""Structured Logging and Sensitive Data Redaction for Tollgate."""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tollgate_core.observability.tracer import get_current_span_id, get_current_trace_id

# Context variables for request-scoped correlation
current_request_id: ContextVar[Optional[str]] = ContextVar("current_request_id", default=None)
current_tenant_id: ContextVar[Optional[str]] = ContextVar("current_tenant_id", default=None)
current_project_id: ContextVar[Optional[str]] = ContextVar("current_project_id", default=None)

# Redaction patterns for secrets
REDACTION_PATTERNS = [
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"tg_(?:live|test)_[a-zA-Z0-9_\-]+"), "tg_[REDACTED]"),
    (re.compile(r"sk-[a-zA-Z0-9_\-]+"), "sk-[REDACTED]"),
    (re.compile(r"password=([^&\s]+)", re.IGNORECASE), "password=[REDACTED]"),
    (re.compile(r"client_secret=([^&\s]+)", re.IGNORECASE), "client_secret=[REDACTED]"),
]


def redact_sensitive_text(text: str) -> str:
    """Scans and redacts API keys, tokens, and credentials from a string."""
    if not text:
        return text
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class StructuredLogFormatter(logging.Formatter):
    """
    JSON log formatter correlating request_id, trace_id, span_id, and service identity.
    Redacts sensitive credentials and outputs structured log events.
    """

    def __init__(self, service_name: str = "tollgate-api"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        # 1. Base log entry fields
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
        }

        # 2. Extract correlation identifiers from context and OpenTelemetry
        req_id = getattr(record, "request_id", None) or current_request_id.get()
        if req_id:
            log_entry["request_id"] = req_id

        trace_id = getattr(record, "trace_id", None) or get_current_trace_id()
        if trace_id:
            log_entry["trace_id"] = trace_id

        span_id = getattr(record, "span_id", None) or get_current_span_id()
        if span_id:
            log_entry["span_id"] = span_id

        tenant_id = getattr(record, "tenant_id", None) or current_tenant_id.get()
        if tenant_id:
            log_entry["tenant_id"] = tenant_id

        project_id = getattr(record, "project_id", None) or current_project_id.get()
        if project_id:
            log_entry["project_id"] = project_id

        # 3. Add HTTP / operational attributes if present
        for attr in ["route", "status", "duration_ms", "event_id", "failure_category"]:
            val = getattr(record, attr, None)
            if val is not None:
                log_entry[attr] = val

        # 4. Include exception details if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(
    service_name: str = "tollgate-api",
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configures root logger with structured JSON logging and sensitive data redaction."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(StructuredLogFormatter(service_name=service_name))
    else:
        handler.setFormatter(
            logging.Formatter(f"%(asctime)s [%(levelname)s] [{service_name}] %(message)s")
        )

    root_logger.addHandler(handler)
