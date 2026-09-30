# Tollgate Prometheus Metrics & Cardinality Security Audit

## 1. Objective & Policy

High-cardinality labels in Prometheus create severe memory bloat, degrade scraping performance, and risk Denial of Service (DoS) in monitoring infrastructure. Furthermore, placing customer identifiers (tenant IDs, project IDs, user IDs) or sensitive values (API key IDs, prompt hashes, request IDs, cache keys) in metric labels constitutes a **telemetry data leakage vulnerability**.

### Core Invariant
**No high-cardinality or sensitive identifiers may ever be used as Prometheus metric labels.**

---

## 2. Forbidden Metric Labels Policy

The following labels are strictly forbidden across all Prometheus counters, gauges, and histograms:

| Forbidden Label | Reason | Risk |
| :--- | :--- | :--- |
| `tenant_id` | Multi-tenant isolation & unbounded cardinality | OOM in Prometheus; cross-tenant tenant ID harvesting |
| `project_id` | Unbounded cardinality per tenant | Memory exhaustion; project enumeration |
| `api_key_id` | High churn & sensitive credential reference | Key lifecycle tracking and unbounded label creation |
| `user_id` | Customer personal data (PII) | PII leakage in unauthenticated monitoring endpoints |
| `request_id` | Unique per HTTP request (infinite cardinality) | Immediate Prometheus crash due to millions of time-series |
| `event_id` | Unique per usage event (infinite cardinality) | Severe memory amplification in Prometheus TSDB |
| `trace_id` | Unique per distributed trace | OTel trace context belongs in Jaeger/Tempo, not Prometheus |
| `span_id` | Unique per span execution | Telemetry explosion |
| `cache_key` | Unbounded hash string | Hash table explosion in monitoring store |
| `prompt_hash` | Sensitive customer input derivation | Re-identification / fingerprinting of confidential prompts |
| `client_ip` | Network privacy & unbounded cardinality | GDPR/PII compliance violation |

---

## 3. Allowed Bounded Labels & Normalization

All Prometheus labels in Tollgate are bounded by strict whitelists and normalizers:

| Label Name | Allowed Values | Normalization Rule |
| :--- | :--- | :--- |
| `method` | `GET`, `POST`, `PUT`, `DELETE`, `OPTIONS` | Standard HTTP verbs only |
| `path` | Whitelisted route prefixes (e.g. `/v1/chat/completions`, `/api/v1/dashboard`) | `normalize_route(path)`: dynamic path params are collapsed |
| `status_code` | `200`, `400`, `401`, `402`, `403`, `404`, `429`, `500`, `502`, `504` | Standard integer HTTP status codes |
| `provider` | `openai`, `anthropic`, `mock`, `gemini`, `cohere` | Lowercase provider identifier from registry |
| `model` | Known model identifiers (`gpt-4o`, `mock-model`, `claude-3-5-sonnet`, etc.) | `normalize_model(model)`: unknown custom models map to `other` |
| `category` | `authentication`, `authorization`, `validation`, `rate_limit`, `budget`, `internal` | `KNOWN_ERROR_CATEGORIES` enum |
| `status` | `success`, `failure`, `timeout`, `open`, `closed`, `half_open` | Static state enumeration |
| `router_route`| `cheap`, `strong`, `passthrough`, `fallback` | Static routing tier name |
| `cache_type` | `exact`, `semantic` | Static cache classification |

---

## 4. Metric Declarations Audit

Every declared Prometheus metric in `packages/core/src/tollgate_core/observability/metrics.py` was inspected:

### HTTP Traffic & Latency
- `tollgate_http_requests_total`: Labels `['method', 'path', 'status_code']` — **PASSED** (Path is normalized via `normalize_route`).
- `tollgate_http_request_duration_seconds`: Labels `['method', 'path']` — **PASSED**.

### Provider Health & Reliability
- `tollgate_provider_requests_total`: Labels `['provider', 'model', 'status']` — **PASSED**.
- `tollgate_provider_latency_seconds`: Labels `['provider', 'model']` — **PASSED**.
- `tollgate_circuit_breaker_state`: Labels `['provider']` — **PASSED**.
- `tollgate_circuit_breaker_transitions_total`: Labels `['provider', 'from_state', 'to_state']` — **PASSED**.

### Exact & Semantic Cache
- `tollgate_cache_lookups_total`: Labels `['cache_type', 'status']` — **PASSED**.
- `tollgate_cache_lookup_duration_seconds`: Labels `['cache_type']` — **PASSED**.
- `tollgate_cache_invalidations_total`: Labels `['cache_type']` — **PASSED**.

### Rate Limiting & Budgets
- `tollgate_rate_limit_checks_total`: Labels `['status']` — **PASSED**.
- `tollgate_budget_checks_total`: Labels `['scope', 'status']` — **PASSED**.
- `tollgate_budget_settlements_total`: Labels `['status']` — **PASSED**.

### Errors
- `tollgate_errors_total`: Labels `['category', 'status_code']` — **PASSED** (Category is restricted to `KNOWN_ERROR_CATEGORIES`).

---

## 5. Security & Verification Conclusion

All metric label definitions in Tollgate comply with zero-tenant-leakage and bounded-cardinality requirements. The metrics scrape endpoint (`/metrics`) is protected with bearer token authentication (`settings.metrics_token`) when `settings.metrics_auth_enabled=True`.
