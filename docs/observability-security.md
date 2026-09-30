# Observability Security and Redaction Policy

## Overview

Distributed tracing and structured logging provide operational visibility into Tollgate's routing, caching, rate limiting, and provider reliability. However, in an LLM gateway environment, telemetry must never become a vector for credential leakage or data privacy violations.

Tollgate enforces strict data sanitization, redaction, and access controls across all traces, span attributes, and log messages.

---

## 1. What Telemetry Contains

Tollgate telemetry is strictly operational and metadata-oriented. Permitted telemetry data includes:

### Traces and Spans
- **Request Identifiers**: Application `request_id` (`req_<hex>`) and distributed tracing IDs (`trace_id`, `span_id`).
- **Tenancy Scopes**: `tenant_id`, `project_id`, authenticated `role` (`owner`, `admin`, `member`).
- **HTTP Transport Attributes**: Method (`POST`), route (`/v1/chat/completions`), status code (`200`, `429`, `502`, etc.), total execution duration in milliseconds.
- **Provider & Model Routing Metadata**:
  - Configured model aliases (`mock-model`, `gpt-4o`, `claude-3-5-sonnet`).
  - Target provider names (`openai`, `anthropic`, `mock`).
  - Model router mode (`disabled`, `static`, `learned`), route classification (`cheap`, `strong`, `fallback`), and model tier confidence score.
  - Upstream provider attempt count, retry attempt number, backoff delay in seconds, and normalized failure category (e.g. `rate_limit`, `timeout`, `service_unavailable`).
  - Fallback transition details (`from_provider`, `to_provider`, `fallback_model`).
- **Cache Operation Metadata**:
  - Cache lookup type (`exact` or `semantic`).
  - Cache outcome (`hit: true` or `hit: false`).
  - Safe bypass reason (e.g. `not_cacheable`, `temperature_nonzero`).
- **Budget Operational Metadata**:
  - Reservation ID, reservation outcome (`budget.allowed: true|false`), budget scope (`tenant` or `project`).
- **Streaming Metrics**:
  - Time to first token (`tollgate.time_to_first_token_ms`).
  - Overall stream duration (`tollgate.stream_duration_ms`).
  - Number of SSE chunks emitted.

### Structured Logs
- Event timestamps (ISO 8601 UTC).
- Log level (`INFO`, `WARNING`, `ERROR`).
- Service identifier (`tollgate-api` or `tollgate-worker`).
- Correlated `request_id`, `trace_id`, `span_id`.
- Sanitized operational messages and system lifecycle events.

---

## 2. What Is Strictly Excluded

Tollgate strictly prohibits and programmatically blocks the following categories of data from traces, spans, and logs:

| Category | Excluded Elements | Mitigation Mechanism |
| :--- | :--- | :--- |
| **Authentication & Credentials** | API Keys (`tg_live_...`, `tg_test_...`), Bearer tokens, Authorization headers, OpenAI/Anthropic/Provider API keys, client secrets | `safe_set_attribute` regex filter + `redact_sensitive_text` log filter |
| **User Prompts** | Chat completion prompt texts, system prompts, user query contents | Explicitly barred from span attributes and log statements |
| **Model Responses** | Generated LLM completion texts, streaming text fragments | Explicitly barred from span attributes and log statements |
| **Tool Arguments & Calls** | Function arguments, tool inputs, parameter JSON | Attribute key names matching `tool_args`, `arguments` are blocked |
| **Vector Embeddings** | High-dimensional embedding vectors used in semantic cache | Attribute key names matching `embedding` are blocked |
| **Infrastructure Secrets** | Database passwords, Redis passwords, connection string credentials | Regex pattern redaction (`password=[REDACTED]`, `client_secret=[REDACTED]`) |

---

## 3. Why Sensitive Request Content Is Excluded

1. **Multi-Tenant Privacy Isolation**: Tollgate serves multiple corporate tenants and projects. Telemetry storage (Jaeger, OpenSearch, Datadog) is centralized. Including raw prompts or completions in traces would expose sensitive customer conversations across tenancy boundaries to operations and DevOps personnel.
2. **Regulatory Compliance (GDPR, HIPAA, CCPA)**: End-user prompts may contain Personally Identifiable Information (PII) or Protected Health Information (PHI). Preventing prompts from entering traces ensures telemetry repositories remain outside the scope of PII retention and "right to be forgotten" requests.
3. **Data Minimization & High Cardinality Overhead**: Prompts, embeddings, and responses have unboundedly large byte sizes. Storing raw tokens and vectors in distributed trace backends causes unbounded memory growth, slow trace indexing, and excessive infrastructure costs.

---

## 4. Redaction Mechanisms

Tollgate implements defense-in-depth sanitization:

1. **`safe_set_attribute(span, key, value)`**:
   - Inspects attribute keys against blacklisted patterns: `api_key`, `authorization`, `bearer`, `password`, `secret`, `prompt`, `response_body`, `content`, `embedding`, `credential`, `tool_args`, `arguments`. Any matching key is dropped entirely.
   - Inspects values against regex patterns: `tg_(?:live|test)_[a-zA-Z0-9_\-]+`, `Bearer\s+[a-zA-Z0-9_\-\.]+`, `sk-[a-zA-Z0-9_\-]+`. Matching tokens are replaced with `[REDACTED]`.
2. **`redact_sensitive_text(text)`**:
   - Integrated into `StructuredLogFormatter`. All log messages pass through regex scrubbers before serialization to JSON streams.

---

## 5. Production Retention and Access Considerations

For production deployments:
1. **Role-Based Access Control (RBAC)**: Telemetry systems (Jaeger UI, OTLP collectors, Grafana) must be protected with SSO/OAuth2 and restricted to authorized site reliability engineering (SRE) and operations teams.
2. **Retention Policy**:
   - High-rate distributed traces should have a short retention window (typically 3 to 7 days).
   - Aggregated metrics and daily rollups should be retained long-term in PostgreSQL.
3. **Sampling**: In high-throughput environments, set `TOLLGATE_OTEL_TRACE_SAMPLE_RATE` (e.g. `0.05` to `0.20`) to sample a deterministic fraction of requests while capturing 100% of error traces via parent-based sampling.
