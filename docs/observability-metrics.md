# Phase 11B — Prometheus Metrics & Grafana Dashboards

Production-grade Prometheus metrics, bounded-cardinality instrumentation, and Grafana operational dashboards for the Tollgate LLM gateway.

This document covers metric definitions, label safety, configuration, dashboard layout, alerting recommendations, and operational troubleshooting.

---

## 1. Architecture Overview

Tollgate's metrics pipeline follows a pull-based Prometheus model:

```text
┌─────────────┐     GET /metrics       ┌──────────────┐
│  Gateway    │ ◄─────────────────────  │  Prometheus  │
│  (FastAPI)  │  Bearer token auth      │  (scrape)    │
└─────────────┘                         └──────┬───────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │   Grafana     │
                                        │  (dashboards) │
                                        └──────────────┘
```

Key design principles:
- **Zero crash guarantee**: All metric recording helpers wrap operations in try/except. Telemetry failures never propagate to callers.
- **Bounded cardinality**: High-cardinality values (tenant_id, project_id, api_key_id, request_id, trace_id, prompt) are **NEVER** used as Prometheus labels.
- **Fail-safe `/metrics` endpoint**: Secured with Bearer token or X-Metrics-Token header, configurable via environment variables.
- **Separation of concerns**: Phase 10 PostgreSQL dashboard handles tenant-level analytics. Grafana handles infrastructure and performance metrics.

---

## 2. Metric Families

### 2.1 Gateway HTTP Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_http_requests_total` | Counter | `method`, `route`, `status_class` | Total HTTP requests handled |
| `tollgate_http_request_duration_seconds` | Histogram | `method`, `route`, `status_class` | Request latency distribution |

### 2.2 Provider Reliability Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_provider_requests_total` | Counter | `provider`, `model`, `status_class` | Upstream provider requests |
| `tollgate_provider_errors_total` | Counter | `provider`, `model`, `status_class`, `failure_category` | Provider failures |
| `tollgate_provider_retries_total` | Counter | `provider`, `model` | Retry attempts |
| `tollgate_provider_fallbacks_total` | Counter | `provider`, `target_provider` | Failover events |
| `tollgate_provider_timeouts_total` | Counter | `provider`, `model` | Timeout events |
| `tollgate_provider_request_duration_seconds` | Histogram | `provider`, `model`, `status_class` | Provider call latency |

### 2.3 Cache Metrics (Exact & Semantic)

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_cache_requests_total` | Counter | `cache_type`, `result` | Cache lookups (hit/miss/bypass) |
| `tollgate_cache_errors_total` | Counter | `cache_type`, `operation` | Cache errors |
| `tollgate_cache_operation_duration_seconds` | Histogram | `cache_type`, `operation` | Cache operation latency |
| `tollgate_cache_similarity_score` | Histogram | `cache_type` | Semantic similarity score distribution |

### 2.4 Learned Model Router Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_router_decisions_total` | Counter | `mode`, `route` | Routing decisions (cheap/strong/passthrough) |
| `tollgate_router_errors_total` | Counter | `mode`, `error_type` | Router errors |
| `tollgate_router_fallbacks_total` | Counter | `mode` | Router fallbacks |
| `tollgate_router_decision_duration_seconds` | Histogram | `mode`, `stage` | Router latency |
| `tollgate_router_confidence_score` | Histogram | `mode` | Confidence score distribution |

### 2.5 Budget Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_budget_reservations_total` | Counter | `status` | Reservation attempts (allowed/rejected) |
| `tollgate_budget_reservation_failures_total` | Counter | `reason` | Reservation failures |
| `tollgate_budget_settlements_total` | Counter | `status` | Settlement operations |
| `tollgate_budget_releases_total` | Counter | `status` | Release operations |
| `tollgate_budget_operation_duration_seconds` | Histogram | `operation` | Budget operation latency |

### 2.6 Redis Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_redis_operations_total` | Counter | `operation`, `component`, `status` | Redis command counts |
| `tollgate_redis_operation_duration_seconds` | Histogram | `operation`, `component` | Redis operation latency |
| `tollgate_redis_errors_total` | Counter | `operation`, `component` | Redis command failures |

### 2.7 Usage Worker & Queue Health Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_usage_events_consumed_total` | Counter | `stream` | Events read from Redis Stream |
| `tollgate_usage_events_processed_total` | Counter | `status` | Events persisted to PostgreSQL |
| `tollgate_usage_events_failed_total` | Counter | `failure_type` | Event processing failures |
| `tollgate_usage_events_reclaimed_total` | Counter | — | Reclaimed stale messages |
| `tollgate_usage_events_dead_lettered_total` | Counter | `reason` | Dead-lettered events |
| `tollgate_usage_processing_duration_seconds` | Histogram | `status` | Event processing latency |
| `tollgate_usage_queue_pending_messages` | Gauge | `stream` | Pending unacknowledged messages |
| `tollgate_usage_dead_letter_queue_messages` | Gauge | `stream` | Dead-letter queue depth |

### 2.8 Streaming Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_stream_requests_total` | Counter | `provider`, `model` | SSE streaming requests |
| `tollgate_stream_duration_seconds` | Histogram | `provider`, `model`, `status` | Full stream duration |
| `tollgate_stream_time_to_first_token_seconds` | Histogram | `provider`, `model` | Time to first token (TTFT) |
| `tollgate_stream_disconnects_total` | Counter | `reason` | Client disconnects |
| `tollgate_stream_failures_total` | Counter | `failure_class` | Stream failure classifications |

### 2.9 Error Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_errors_total` | Counter | `category`, `status_code` | Normalized error counts |

### 2.10 Infrastructure Health Metrics

| Metric | Type | Labels | Description |
|:---|:---|:---|:---|
| `tollgate_infrastructure_redis_healthy` | Gauge | — | Redis health (1.0/0.0) |
| `tollgate_infrastructure_postgres_healthy` | Gauge | — | PostgreSQL health (1.0/0.0) |
| `tollgate_infrastructure_postgres_pool_size` | Gauge | — | DB pool capacity |
| `tollgate_infrastructure_postgres_pool_checkedout` | Gauge | — | DB pool connections in use |

---

## 3. Bounded Cardinality Strategy

All label values pass through normalization functions that restrict cardinality:

| Normalizer | Input | Bounded Output |
|:---|:---|:---|
| `normalize_route(path)` | Any HTTP path | Whitelist match → exact path; prefix match → prefix; else `"other"` |
| `normalize_model(model)` | Any model string | Whitelist match → model name; prefix match → base model; else `"custom"` |
| `status_code_to_class(code)` | HTTP status code | `"2xx"`, `"3xx"`, `"4xx"`, `"5xx"`, `"unknown"` |
| `normalize_error_category(cat)` | Any error string | Whitelist match → category; else `"internal"` |

**Whitelisted models**: gpt-4o, gpt-4o-mini, gpt-4, gpt-3.5-turbo, claude-3-5-sonnet, claude-3-haiku, claude-3-opus, gemini-1.5-pro, gemini-1.5-flash, text-embedding-3-small, text-embedding-3-large, mock-model, mock-fast.

**Whitelisted error categories**: authentication, authorization, validation, rate_limit, budget, cache, provider_timeout, provider_rate_limit, provider_auth, provider_not_found, provider_content, provider_internal, internal.

---

## 4. Configuration

| Environment Variable | Default | Purpose |
|:---|:---|:---|
| `TOLLGATE_METRICS_ENABLED` | `true` | Enable/disable the `/metrics` endpoint |
| `TOLLGATE_METRICS_AUTH_ENABLED` | `true` | Require authentication on `/metrics` |
| `TOLLGATE_METRICS_TOKEN` | — | Bearer token or X-Metrics-Token value |

---

## 5. `/metrics` Endpoint

```
GET /metrics
Authorization: Bearer <TOLLGATE_METRICS_TOKEN>
```

Or:
```
GET /metrics
X-Metrics-Token: <TOLLGATE_METRICS_TOKEN>
```

Returns: `text/plain; version=0.0.4; charset=utf-8` (Prometheus exposition format)

---

## 6. Grafana Dashboards

Five pre-provisioned dashboards are auto-loaded into Grafana:

| Dashboard | File | Panels |
|:---|:---|:---|
| **Gateway Overview** | `gateway.json` | Request rate, latency percentiles (p50/p95/p99), error rate, status distribution |
| **Provider Reliability** | `provider_reliability.json` | Provider request rate, error rate by provider/model, retry and fallback rates, timeout rates, latency distribution |
| **Cache Performance** | `cache.json` | Hit rate (exact + semantic), operation latency, error rate, similarity score distribution |
| **Infrastructure Health** | `infrastructure.json` | Redis/Postgres health, Redis operation latency, DB connection pool usage, queue depth, dead letter count |
| **Usage Worker** | `usage_worker.json` | Events consumed/processed rate, failure rate, processing latency, reclaimed events, dead-letter trend |

---

## 7. Docker Compose Setup

```bash
docker compose up -d
```

Services:
- **Prometheus**: `http://localhost:9090` (bound to localhost only)
- **Grafana**: `http://localhost:3001` (admin/tollgate_admin_pass)
- **Jaeger**: `http://localhost:16686`

Prometheus scrapes the gateway's `/metrics` endpoint every 5 seconds with the configured Bearer token.

Grafana auto-provisions the Prometheus datasource and all five dashboards on first boot.

---

## 8. Alerting Recommendations

| Alert | PromQL | Severity |
|:---|:---|:---|
| High error rate | `rate(tollgate_http_requests_total{status_class="5xx"}[5m]) / rate(tollgate_http_requests_total[5m]) > 0.05` | Critical |
| Provider degradation | `rate(tollgate_provider_errors_total[5m]) / rate(tollgate_provider_requests_total[5m]) > 0.1` | Warning |
| Cache miss spike | `rate(tollgate_cache_requests_total{result="miss"}[5m]) / rate(tollgate_cache_requests_total[5m]) > 0.95` | Warning |
| High queue depth | `tollgate_usage_queue_pending_messages > 1000` | Warning |
| Dead letter growth | `rate(tollgate_usage_events_dead_lettered_total[15m]) > 0` | Critical |
| Redis unhealthy | `tollgate_infrastructure_redis_healthy == 0` | Critical |
| Postgres unhealthy | `tollgate_infrastructure_postgres_healthy == 0` | Critical |
| High TTFT | `histogram_quantile(0.95, rate(tollgate_stream_time_to_first_token_seconds_bucket[5m])) > 3` | Warning |

---

## 9. Troubleshooting

### Metrics endpoint returns 401
- Verify `TOLLGATE_METRICS_AUTH_ENABLED` and `TOLLGATE_METRICS_TOKEN` environment variables.
- Prometheus's `bearer_token` in `prometheus.yml` must match the gateway's `TOLLGATE_METRICS_TOKEN`.

### No data in Grafana
1. Check Prometheus targets: `http://localhost:9090/targets`
2. Verify the gateway target shows `State: UP`.
3. Check Grafana datasource connectivity in Settings → Data Sources.

### High cardinality warnings
- Never add tenant_id, project_id, api_key_id, or request_id as Prometheus labels.
- If custom models are used, they will be normalized to `"custom"` to prevent cardinality explosion.

### Metric recording failures
- All recording helpers log failures at `DEBUG` level.
- Check gateway logs: `grep "Failed to record" gateway.log`
