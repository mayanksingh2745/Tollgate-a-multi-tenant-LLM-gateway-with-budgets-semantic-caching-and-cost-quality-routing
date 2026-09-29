# Tollgate: Multi-Tenant LLM Gateway

[![CI Pipeline](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions/workflows/ci.yml/badge.svg)](https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)](https://react.dev/)

Tollgate is an enterprise-grade multi-tenant LLM gateway designed to prevent runaway costs, enforce per-project monthly budgets, provide automatic provider failover, enable high-performance semantic caching, and maintain token accounting precision across streaming and concurrent workloads.

---

---

## Feature Status

- ✓ Multi-tenancy
- ✓ API key authentication
- ✓ OpenAI-compatible API
- ✓ Streaming
- ✓ Provider retries
- ✓ Provider failover
- ✓ Distributed rate limiting
- ✓ Atomic budget reservation
- ✓ Usage event pipeline
- ✓ Redis Streams
- ✓ Background worker
- ✓ PostgreSQL usage records
- ✓ Daily/monthly cost rollups
- ✓ Exact response caching

## Implemented Phases

- **Phase 0 — Engineering Foundation**: FastAPI, AsyncPG, Redis, React Dashboard, Docker Compose, Alembic.
- **Phase 1 — Multi-Tenancy & API Key Authentication**: Tenant & Project hierarchy, RBAC (`owner`, `admin`, `viewer`), secure API key generation & constant-time hash verification.
- **Phase 2 — OpenAI-Compatible LLM Gateway**: `/v1/chat/completions` proxy supporting standard OpenAI client SDKs, non-streaming & SSE streaming, provider abstraction, request tracking, and timeouts.
- **Phase 3 — Provider Reliability, Retries & Failover**: Centralized failure classification, exponential backoff with bounded jitter, overall request deadlines, deterministic fallback chains, streaming failure safety, and lightweight provider health tracking.
- **Phase 4 — Distributed Rate Limiting**: Distributed, concurrency-safe token bucket rate limiting using Redis and an atomic Lua script, burst capacity, continuous token refill, explicit fail-open/fail-closed modes, standard `X-RateLimit-*` headers, and HTTP 429 enforcement.
- **Phase 5 — Budget Reservation & Settlement**: Atomic two-phase budget reservation and settlement, multi-scope spending limits (Tenant & Project daily/monthly), integer microdollar arithmetic ($1.00 = 1,000,000), pre-request cost estimation, idempotent settlement with refunding, and HTTP 402 enforcement.
- **Phase 6 — Usage Pipeline & Cost Accounting**: Asynchronous, durable usage ingestion via Redis Streams (`tg:usage:events`), consumer group background workers, crash recovery with `XAUTOCLAIM`, PostgreSQL event persistence, idempotent daily & monthly rollups, and paginated tenant-isolated usage query APIs.
- **Phase 7 — Exact Response Cache**: High-performance, tenant-isolated exact-match response caching in Redis with SHA-256 canonicalization, O(1) project cache invalidation via generation counters, fail-open resilience, zero budget/usage overhead on hit, and `X-Tollgate-Cache` observability headers.

---

## Exact Response Cache

Tollgate intercepts identical chat completion requests in Redis to eliminate upstream provider latency and cost while preserving strict tenant isolation:

```text
Client Request
      ↓
API Key Authentication
      ↓
Distributed Rate Limiting (Token Bucket)
      ↓
Exact Response Cache Lookup
      ├── HIT  ──► Return Cached Response + X-Tollgate-Cache: HIT
      │            ($0.00 provider cost, zero budget reservation)
      └── MISS ──► Budget Reservation ──► Upstream Provider ──► Cache Write ──► Usage Event
```

### Key Capabilities
- **Deterministic SHA-256 Canonicalization**: Preserves message order and semantic whitespace while sorting object keys and normalizing default sampling parameters (`temperature`, `top_p`, `seed`, `max_tokens`).
- **Strict Tenant & Project Isolation**: Keys are scoped to `tg:cache:{tenant_id}:{project_id}:{version}:{digest}`. Overages, entries, or invalidations in one tenant or project never cross isolation boundaries.
- **O(1) Project-Wide Invalidation**: Invalidation increments a Redis generation counter (`tg:cache:ver:{tenant_id}:{project_id}`). All previous entries for that project immediately become unreachable in $O(1)$ time with zero Redis key scanning.
- **Safe Bypass Policy**: Requests with `stream: true`, tool definitions (`tools`), or explicit non-deterministic configurations automatically bypass caching with `X-Tollgate-Cache: BYPASS`.
- **Zero Budget & Token Consumption on Hits**: Cache hits do not reserve or settle budgets, emit fake provider usage events, or incur upstream costs.
- **Fail-Open Resilience**: Any Redis network failure or payload corruption fails open, immediately routing the request to the upstream provider without client disruption.

See [`docs/exact-cache.md`](docs/exact-cache.md) for complete architecture, canonicalization rules, and benchmark measurements.

---

## Usage Pipeline & Cost Accounting

Tollgate uses an asynchronous Redis Stream and consumer-group pipeline to record request usage and financial accounting without burdening the synchronous gateway request path:

```text
Gateway Request Path                   Asynchronous Worker Path
────────────────────                   ────────────────────────
Client Request
      ↓
Authentication & Rate Limit
      ↓
Budget Reservation
      ↓
Upstream Provider Execution
      ↓
Response Completion / Settlement
      ↓
Emit Usage Event ──(XADD)──► Redis Stream (tg:usage:events)
                                       ↓
                             Consumer Group (tg-usage-workers)
                                       ↓
                             Background Worker
                                       ↓
                             Atomic PostgreSQL Transaction
                               ├─ usage_events (ON CONFLICT DO NOTHING)
                               ├─ usage_daily_rollups
                               └─ usage_monthly_rollups
                                       ↓
                             XACK Message
```

### Key Capabilities
- **Decoupled Persistence**: No synchronous database writes in the critical gateway request path.
- **Redis Streams & Consumer Groups**: Workload distributed among worker replicas with pending entry tracking (PEL).
- **Crash Recovery & Reclaims**: Unacknowledged messages from crashed workers are reclaimed via `XAUTOCLAIM`.
- **Database-Level Idempotency**: `UNIQUE(event_id)` and conditional rollup updates guarantee rollups never double-count duplicate deliveries.
- **Dead-Letter Quarantine**: Permanently malformed events are moved to `tg:usage:dead-letter` without blocking stream progress.
- **Tenant-Isolated Analytics**: Paginated `GET /api/v1/usage` with cursor pagination, plus daily and monthly rollup query endpoints.

See [`docs/usage-pipeline.md`](docs/usage-pipeline.md) for detailed schema specifications and consistency boundaries.

---

## Budgets & Spending Controls

Tollgate enforces strict monetary spending limits to prevent runaway provider costs, even under massive concurrent request volume:

```
Request arrives
    ↓
Estimate maximum cost
    ↓
Atomically reserve budget (Redis Lua)
    ↓
Call upstream provider
    ↓
Receive actual token usage
    ↓
Settle reservation & refund unused budget
```

### Key Capabilities
- **Atomic Two-Phase Protocol**: Pre-reserves maximum estimated cost before provider invocation; settles actual usage and refunds the difference post-completion.
- **Multi-Scope Hierarchy**: Enforces limits across Tenant Daily, Tenant Monthly, Project Daily, and Project Monthly budgets simultaneously in a single atomic Lua transaction.
- **Exact Monetary Precision**: Zero floating-point drift. All values are represented in integer microdollars ($1.00 = 1,000,000).
- **Leak-Proof Lease Expiration**: Stale reservations from crashed workers expire automatically after lease TTL and return reserved capacity to the pool.
- **Idempotent Settlement**: Settle operations can be safely retried without double-charging accounts.
- **Differentiated Error Handling**: Returns HTTP 402 Payment Required for exhausted budgets, strictly separating spending limits from HTTP 429 rate limits.

See [`docs/budgets.md`](docs/budgets.md) for complete architecture, pricing models, and Lua script designs.

---

## Rate Limiting

Tollgate enforces distributed, concurrency-safe rate limits using Redis before requests consume upstream LLM capacity:

```
Client Request
      ↓
API Key Authentication
      ↓
Atomic Redis Token Bucket (Lua)
      ├─ Sufficient tokens → Decrement token → Forward to Provider
      └─ Bucket exhausted  → Reject with HTTP 429 Too Many Requests
```

### Key Capabilities
- **Redis Token Bucket**: Supports continuous token refills at sustained rate ($R$) while accommodating instantaneous burst bursts ($B$).
- **Atomic Lua Evaluation**: Check, refill, consumption, and expiration happen atomically in Redis, preventing race conditions across multiple gateway instances.
- **Rate Limit Headers**: Injects `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` into all 200 and 429 responses, plus `Retry-After` on 429s.
- **API Key Scoped Isolation**: Buckets are scoped strictly per authenticated API key ID (`tg:ratelimit:apikey:{id}`). Overages on one key never affect others.
- **Configurable Redis Failure Modes**: Supports both `closed` (rejects requests on Redis unavailability to protect upstream costs) and `open` (permits requests during outages to prioritize availability).

See [`docs/rate_limiting.md`](docs/rate_limiting.md) for detailed formulas, Lua script logic, and configuration options.

---

## Reliability

Tollgate's reliability layer guarantees resilient upstream execution when interacting with third-party LLM providers:

```
Provider A
  ↓
timeout
  ↓
retry
  ↓
failure
  ↓
Provider B
  ↓
success
```

### Key Capabilities
- **Retry Policy**: Bounded retries (default: 3 max attempts including initial attempt). Non-retryable errors (`400 Bad Request`, `401 Unauthorized`) fail immediately without consuming retry quotas.
- **Exponential Backoff**: Async sleep delays calculated as $\min(\text{max\_delay}, \text{base\_delay} \times 2^{\text{attempt}-1})$. Never blocks the event loop.
- **Jitter**: Bounded random variance applied to prevent synchronized thundering herds against recovering upstream APIs.
- **Overall Request Deadlines**: Bounded total request lifespan (`TOLLGATE_REQUEST_TIMEOUT_SECONDS`) prevents unbounded retries from accumulating.
- **Retry-After Compliance**: HTTP 429 rate limit responses with `Retry-After` headers are respected within configured ceiling bounds.
- **Deterministic Provider Fallback**: When a primary provider fails transiently or becomes exhausted, requests fail over to configured secondary providers in deterministic order.
- **Streaming Safety**: If an upstream failure occurs *before* any chunks are emitted to the client, retries or fallbacks proceed safely. If a failure occurs *after* streaming output has begun, Tollgate safely terminates the stream rather than transparently restarting, avoiding duplicated or inconsistent model output.
- **Provider Health Tracking**: Consecutive failures temporarily mark providers as degraded, with automatic single-probe recovery after cooldown.

> **Note**: Tollgate is inspired by and compared conceptually with existing LLM gateways (such as LiteLLM, Portkey, and Kong AI Gateway). The project's objective is engineering depth, architectural transparency, and verifiable, measurable behavior under fault conditions rather than claiming that provider failover itself is novel.

See [`docs/reliability.md`](docs/reliability.md) for full architecture, state diagrams, and failure classification rules.

---

## OpenAI-Compatible Gateway (`/v1/chat/completions`)

Tollgate acts as a drop-in replacement for any OpenAI-compatible API. Point your OpenAI SDK or HTTP client directly to Tollgate:

### Python Example (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="tg_live_your_tollgate_api_key_here",
    base_url="http://localhost:8000/v1"
)

# Non-streaming request
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explain asynchronous programming in Python"}],
    stream=False
)
print(response.choices[0].message.content)

# Streaming request (SSE)
stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Count from 1 to 5"}],
    stream=True
)
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

See [`docs/gateway.md`](docs/gateway.md) for full endpoint specifications, streaming lifecycle, and timeout configurations.

---

## API Reference

### Gateway
- `POST /v1/chat/completions` — OpenAI-compatible chat completions (Non-streaming & SSE Streaming)

### Multi-Tenancy & Identity (Phase 1)
- `POST /api/v1/tenants` — Create tenant
- `GET /api/v1/tenants/{tenant_id}` — Get tenant details
- `POST /api/v1/tenants/{tenant_id}/users` — Create user (Argon2id password hashing)
- `GET /api/v1/tenants/{tenant_id}/users` — List users in tenant
- `POST /api/v1/tenants/{tenant_id}/projects` — Create project
- `GET /api/v1/tenants/{tenant_id}/projects` — List projects in tenant
- `POST /api/v1/projects/{project_id}/api-keys` — Generate API key (Raw secret returned **ONLY ONCE**)
- `GET /api/v1/projects/{project_id}/api-keys` — List API key metadata
- `DELETE /api/v1/api-keys/{api_key_id}` — Revoke API key
- `POST /api/v1/api-keys/{api_key_id}/rotate` — Rotate API key

### Usage & Cost Accounting (Phase 6)
- `GET /api/v1/usage` — Paginated list of usage records (cursor-based, filtered by tenant, project, date range, provider, model)
- `GET /api/v1/usage/rollups/daily` — Aggregated daily usage & cost rollups
- `GET /api/v1/usage/rollups/monthly` — Aggregated monthly usage & cost rollups

### Exact Response Cache (Phase 7)
- `DELETE /api/v1/projects/{project_id}/cache` — Invalidate project cache (O(1) generation counter increment, requires `owner` or `admin` role)

---

## Quick Start (Docker Compose)

Launch the complete stack (FastAPI + PostgreSQL + Redis + Worker + React Dashboard) with a single command:

```bash
docker compose up --build
```

---

## Local Development & Testing

```bash
# Run complete test suite (unit + integration + OpenAI SDK compatibility)
pytest
```
