# Phase 11A — OpenTelemetry, Distributed Tracing & Log Correlation

Tollgate incorporates production-grade distributed tracing and structured log correlation using OpenTelemetry (OTel) and W3C context propagation standards.

This document details the distributed tracing architecture, span hierarchies, log correlation mechanisms, configuration options, local Docker Compose setup, and operational troubleshooting.

---

## 1. Observability Architecture

Tollgate follows a zero-hard-dependency observability paradigm:
- **Resilience**: The gateway and worker continue operating with zero disruption if the OTLP telemetry backend or network collector becomes unavailable. Telemetry export uses bounded in-memory queues and explicit network timeouts.
- **Trace Context Propagation**: Adheres to the W3C TraceContext recommendation (`traceparent` and `tracestate`). Inbound traces are seamlessly linked to downstream provider calls and asynchronous Redis Stream events.
- **Correlation**: Maintains distinct application correlation (`request_id`, e.g. `req_abc123`) alongside distributed tracing (`trace_id`, 32-hex character W3C ID) and span identity (`span_id`).

### Request Trace Hierarchy

A typical chat completion request executes through the following span tree:

```text
gateway.request (HTTP route, request_id, tenant_id, project_id, status_code)
├── authenticate (api_key verification, role, success)
├── rate_limit (token bucket evaluation, remaining, limits)
├── cache.lookup (exact / semantic cache check, hit: true|false)
├── router.decision (learned router tier, confidence, selected_model)
├── budget.reserve (atomic multi-scope balance reservation)
├── provider.request (upstream execution, stream flag)
│   ├── provider.attempt (latency, attempt count, upstream model, TTFT)
│   ├── provider.retry (backoff delay, retryable failure category)
│   └── provider.fallback (deterministic failover target)
├── budget.settle (settlement with actual token cost)
├── cache.write (indexing into exact and semantic caches)
└── usage.publish (asynchronous event dispatch with traceparent)
```

### Asynchronous Usage Worker Trace Hierarchy

Because Redis Streams operate asynchronously, the gateway does not pretend the background worker is synchronous. The traceparent is propagated within the `UsageEventPayload`:

```text
gateway
   │
   └── usage.publish (injects traceparent, trace_id, span_id)
          │
          ▼
      Redis Stream (tg:usage:events)
          │
          ▼
      worker
          ├── usage.process (extracts traceparent as parent context)
          │     ├── usage.persist (atomic PostgreSQL insert with idempotency)
          │     └── usage.rollup (daily and monthly rollup updates)
```

---

## 2. Standardized Span Names and Safe Attributes

Span names use stable, low-cardinality identifiers:

| Span Name | Description | Attributes Recorded |
| :--- | :--- | :--- |
| `gateway.request` | Root HTTP request span | `http.request.method`, `http.route`, `http.response.status_code`, `tollgate.request_id`, `tollgate.tenant_id`, `tollgate.project_id`, `tollgate.requested_model`, `tollgate.stream` |
| `authenticate` | API key authentication | `auth.type`, `auth.success`, `tollgate.tenant_id`, `tollgate.project_id`, `tollgate.role` |
| `rate_limit` | Distributed rate limiting check | `rate_limit.allowed`, `rate_limit.remaining`, `rate_limit.limit`, `rate_limit.retry_after` |
| `cache.lookup` | Response cache probe | `cache.type` (`exact` or `semantic`), `cache.hit`, `cache.bypass_reason` |
| `cache.write` | Cache indexing operation | `cache.type`, `cache.key` |
| `cache.invalidate` | Project cache invalidation | `tollgate.tenant_id`, `tollgate.project_id`, `cache.type`, `cache.new_version`, `cache.semantic_invalidated` |
| `router.decision` | Learned model router | `router.mode`, `router.route`, `router.confidence`, `router.threshold`, `requested_model`, `selected_model` |
| `budget.reserve` | Atomic spending limit reserve | `reservation_id`, `tollgate.tenant_id`, `tollgate.project_id`, `budget.allowed`, `budget.scope` |
| `budget.settle` | Settle reserved balance | `reservation_id`, `budget.settled` |
| `budget.release` | Release unspent balance | `reservation_id`, `budget.released` |
| `provider.request` | Upstream provider execution | `tollgate.provider`, `tollgate.requested_model`, `tollgate.stream` |
| `provider.attempt` | Single provider attempt | `tollgate.provider`, `tollgate.model`, `tollgate.provider.attempt`, `status`, `duration_ms`, `tollgate.time_to_first_token_ms` (streaming), `tollgate.stream_duration_ms` (streaming), `tollgate.chunks_emitted` |
| `provider.retry` | Retry backoff wait | `tollgate.provider`, `tollgate.provider.retry`, `failure_category`, `retry_delay_seconds` |
| `provider.fallback` | Provider failover trigger | `tollgate.provider.fallback`, `tollgate.fallback.from_provider`, `tollgate.fallback.to_provider`, `tollgate.fallback.model` |
| `usage.publish` | Publishing event to Redis | `tollgate.request_id`, `tollgate.stream`, `tollgate.event_id` |
| `usage.process` | Worker consuming event | `tollgate.request_id`, `tollgate.event_id`, `tollgate.tenant_id`, `tollgate.project_id`, `tollgate.provider`, `tollgate.model` |
| `usage.persist` | DB insert of usage event | `tollgate.event_id`, `tollgate.request_id`, `persisted`, `duplicate` |
| `usage.rollup` | DB rollup increment | `tollgate.event_id`, `tollgate.tenant_id` |

---

## 3. Structured Logging & Correlation

Tollgate formats all application logs as structured JSON strings containing correlation identifiers.

### Log Schema Example

```json
{
  "timestamp": "2026-09-30T10:15:30.123456Z",
  "level": "INFO",
  "service": "tollgate-api",
  "logger": "gateway.src.api.routes.chat",
  "message": "Chat completion fulfilled by primary provider",
  "request_id": "req_a1b2c3d4e5f60718",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "project_id": "22222222-2222-2222-2222-222222222222",
  "route": "/v1/chat/completions",
  "status": 200,
  "duration_ms": 142.5
}
```

### Worker Log Schema

Worker logs correlate the background task back to the originating gateway request:

```json
{
  "timestamp": "2026-09-30T10:15:30.250000Z",
  "level": "INFO",
  "service": "tollgate-worker",
  "logger": "tollgate.worker.consumer",
  "message": "Usage event processed and ACKed",
  "request_id": "req_a1b2c3d4e5f60718",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "99a8b7c6d5e4f3a2",
  "event_id": "33333333-3333-3333-3333-333333333333"
}
```

---

## 4. Configuration

OpenTelemetry settings are configured using Tollgate's centralized settings:

| Environment Variable | Default | Purpose |
| :--- | :--- | :--- |
| `TOLLGATE_OTEL_ENABLED` | `false` | Enable or disable OpenTelemetry tracing globally |
| `TOLLGATE_OTEL_ENDPOINT` | `http://localhost:4318` | Base URL of OTLP HTTP receiver (e.g. Jaeger or OpenTelemetry Collector) |
| `TOLLGATE_OTEL_SERVICE_NAME` | `tollgate-api` | Service name resource identifier (`tollgate-api` for API, `tollgate-worker` for Worker) |
| `TOLLGATE_OTEL_TRACE_SAMPLE_RATE` | `1.0` | Head sampling ratio (`0.0` to `1.0`). Uses `ParentBased` sampling |
| `TOLLGATE_OTEL_EXPORT_TIMEOUT_SECONDS` | `2.0` | Maximum network timeout for span export batches |
| `TOLLGATE_ENVIRONMENT` | `development` | Deployment environment attached to telemetry resource attributes |

---

## 5. Local Setup with Docker Compose

A local Jaeger all-in-one instance is configured in `docker-compose.yml`:

```bash
docker compose up -d
```

Services exposed:
- **Tollgate Gateway API**: `http://localhost:8000`
- **Tollgate Dashboard**: `http://localhost:3000`
- **Jaeger UI**: `http://localhost:16686`
- **OTLP HTTP Receiver**: `http://localhost:4318/v1/traces`
- **OTLP gRPC Receiver**: `localhost:4317`

To inspect traces:
1. Open `http://localhost:16686` in your browser.
2. Select service `tollgate-api` or `tollgate-worker`.
3. Click **Find Traces** to inspect span timelines, latencies, and attributes.

---

## 6. Troubleshooting

### Traces not appearing in Jaeger UI
1. Verify `TOLLGATE_OTEL_ENABLED=true` is set on the container/process.
2. Check connectivity from container to Jaeger: `curl http://jaeger:4318/v1/traces`.
3. Verify sample rate: if `TOLLGATE_OTEL_TRACE_SAMPLE_RATE` is below `1.0`, some traces are unsampled.

### Gateway performance impact
- Span processing uses a bounded background `BatchSpanProcessor` (`max_queue_size=2048`, `schedule_delay_millis=500`). Export occurs in a dedicated thread pool and never blocks HTTP response handlers.
- If the collector becomes slow, batches drop cleanly after `export_timeout_millis` without causing memory leakage.
