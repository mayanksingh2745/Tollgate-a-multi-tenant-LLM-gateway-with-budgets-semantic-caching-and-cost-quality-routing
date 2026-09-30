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
- ✓ Semantic response caching
- ✓ Learned model routing
- ✓ Production dashboard & tenant analytics
- ✓ Advanced benchmarking & evaluation
- ✓ Application & infrastructure security hardening
- ✓ Production deployment, CI/CD & operational readiness
- ✓ High availability & disaster recovery foundation

## Implemented Phases

- **Phase 0 — Engineering Foundation**: FastAPI, AsyncPG, Redis, React Dashboard, Docker Compose, Alembic.
- **Phase 1 — Multi-Tenancy & API Key Authentication**: Tenant & Project hierarchy, RBAC (`owner`, `admin`, `viewer`), secure API key generation & constant-time hash verification.
- **Phase 2 — OpenAI-Compatible LLM Gateway**: `/v1/chat/completions` proxy supporting standard OpenAI client SDKs, non-streaming & SSE streaming, provider abstraction, request tracking, and timeouts.
- **Phase 3 — Provider Reliability, Retries & Failover**: Centralized failure classification, exponential backoff with bounded jitter, overall request deadlines, deterministic fallback chains, streaming failure safety, and lightweight provider health tracking.
- **Phase 4 — Distributed Rate Limiting**: Distributed, concurrency-safe token bucket rate limiting using Redis and an atomic Lua script, burst capacity, continuous token refill, explicit fail-open/fail-closed modes, standard `X-RateLimit-*` headers, and HTTP 429 enforcement.
- **Phase 5 — Budget Reservation & Settlement**: Atomic two-phase budget reservation and settlement, multi-scope spending limits (Tenant & Project daily/monthly), integer microdollar arithmetic ($1.00 = 1,000,000), pre-request cost estimation, idempotent settlement with refunding, and HTTP 402 enforcement.
- **Phase 6 — Usage Pipeline & Cost Accounting**: Asynchronous, durable usage ingestion via Redis Streams (`tg:usage:events`), consumer group background workers, crash recovery with `XAUTOCLAIM`, PostgreSQL event persistence, idempotent daily & monthly rollups, and paginated tenant-isolated usage query APIs.
- **Phase 7 — Exact Response Cache**: High-performance, tenant-isolated exact-match response caching in Redis with SHA-256 canonicalization, O(1) project cache invalidation via generation counters, fail-open resilience, zero budget/usage overhead on hit, and `X-Tollgate-Cache` observability headers.
- **Phase 8 — Semantic Response Cache**: Conservative, tenant-isolated vector response caching using PostgreSQL + pgvector (HNSW cosine index) and decoupled Redis response storage, tiered lookup (Exact L1 -> Semantic L2 -> Upstream L3), deterministic message representation, strict safety bypasses (`stream=true`, `tools`), shadow evaluation mode, offline evaluation harness, and zero budget/usage overhead on hit.
- **Phase 9 — Learned Model Router**: Data-driven, cost-aware model-selection layer predicting whether incoming requests can be satisfied by a fast, cost-efficient model tier (`mock-fast`, `gpt-4o-mini`) or require a strong reasoning model tier (`mock-model`, `gpt-4o`). Features 15 structural/lexical prompt signals, calibrated logistic regression classification, fail-open resilience, shadow evaluation mode, benchmark evaluation suite, and full microdollar cost-quality tradeoff analysis.
- **Phase 10 — Production Dashboard & Tenant Analytics**: Production-grade web interface for tenant owners, admins, and viewers. Features interactive time-series charts (Requests, Tokens, Cost), three-way cost breakdowns, Phase 5 atomic budget monitoring gauges, model and provider reliability telemetry, exact vs semantic cache hit rates & cost avoided, learned model router distribution vs offline evaluation reports, server-side paginated request explorer with safe telemetry detail modals, and project/API-key management.
- **Phase 11A — OpenTelemetry, Distributed Tracing & Log Correlation**: Production-grade distributed tracing with OpenTelemetry across client, cache, router, budget, provider retries, and streaming SSE calls, with W3C TraceContext propagation and correlation IDs.
- **Phase 11B — Prometheus Metrics & Grafana Dashboards**: 35+ operational metrics with bounded label cardinality covering HTTP latencies (p50/p95/p99), provider reliability, exact/semantic caching, router decisions, Redis commands, usage worker queues, and provisioned Grafana dashboards.
- **Phase 12 — Circuit Breaker & Adaptive Provider Health**: 3-state circuit breaker (`CLOSED` → `OPEN` → `HALF_OPEN`) scoped per provider+model, sliding window failure tracking, consecutive 429 rate-limit thresholding, single-probe recovery, fail-open resilience, operator diagnostic endpoint (`GET /internal/provider-health`), and Grafana dashboard panels.
- **Phase 13 — Advanced Benchmarking & Evaluation**: Production-grade, reproducible benchmarking suite measuring real gateway overhead (36 µs), concurrency scaling (up to 1,836 RPS), exact cache hit latency (287 µs), semantic cache precision/recall, router cost savings (42.5%), retry amplification, zero-overspend budget invariants, worker throughput (40,180 eps), and automated regression detection.
- **Phase 14 — Security Hardening**: Application-level security audit (14A) covering authentication, authorization, tenant isolation, request validation, cache security, error leakage, and SQL injection. Infrastructure security (14B) covering dependency auditing, CI/CD hardening, Docker security, container runtime, network exposure, and supply chain integrity.
- **Phase 15 — Production Deployment & Operations**: Production Docker Compose with NGINX reverse proxy, staging environment, automated deployment/rollback/backup/restore scripts, health/readiness/version endpoints, Alembic migration validation, CI/CD pipeline with staging deployment and automated smoke tests, failure injection testing, security validation, and operational drill runbooks.
- **Phase 16A — High Availability & Disaster Recovery Foundation**: Realistic resilience architecture and recovery foundations for the single-host and multi-replica deployment model. Covers 13 failure domains ([`docs/availability-architecture.md`](docs/availability-architecture.md)), rigorous RTO/RPO targets and data store classification ([`docs/recovery-objectives.md`](docs/recovery-objectives.md)), disaster recovery procedures for PostgreSQL, Redis, worker crashed pending events, budget leak prevention, and cold host reconstitution ([`docs/disaster-recovery.md`](docs/disaster-recovery.md)), automated resilience test suite with 22 reproducible failure scenarios ([`docs/resilience-testing.md`](docs/resilience-testing.md)), and expanded incident recovery runbooks ([`docs/operations-runbook.md`](docs/operations-runbook.md)). Multi-instance NGINX upstream load balancing with `least_conn` and automatic 502/503/504 failover.

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

## Semantic Response Cache

Tollgate **Phase 8** introduces a conservative semantic response cache combining **PostgreSQL + pgvector** (HNSW cosine similarity index) for metadata and embeddings, with decoupled **Redis** storage for cached response bodies:

```text
Client Request
      ↓
Authentication & Distributed Rate Limit
      ↓
[Tier 1] Exact Response Cache Lookup (Redis SHA-256 hash, ~0.05ms)
      ├── HIT  ──► Return Cached Response (X-Tollgate-Cache: HIT)
      └── MISS
            ↓
[Tier 2] Semantic Response Cache Lookup (PostgreSQL + pgvector, ~37ms)
      ├── HIT  ──► Return Cached Response (X-Tollgate-Cache: SEMANTIC_HIT)
      └── MISS
            ↓
[Tier 3] Budget Reservation ──► Upstream Provider ──► Dual-Write (L1+L2) ──► Usage Event
```

### Key Capabilities
- **Tiered Lookup Optimization**: Sub-millisecond exact cache check (~0.05 ms) runs before semantic vector lookup (~37 ms), avoiding unnecessary embedding generation when exact matches exist.
- **Decoupled Storage**: PostgreSQL stores embeddings, metadata, and Redis response references (`response_cache_key`). Large LLM response bodies remain strictly in Redis.
- **Conservative Safety Filtering**: Vector proximity alone never triggers a cache hit. Verification requires matching `tenant_id`, `project_id`, `provider`, `model`, and generation controls (`temperature`, `top_p`, `max_tokens`, `stop`, `response_format`).
- **Safety Bypass Policy**: Streaming requests (`stream=true`), requests with tool definitions (`tools`), or sampling multiplicity (`n > 1`) strictly bypass semantic caching.
- **Fail-Open Resilience**: Embedding timeouts, database connection errors, and missing/corrupted Redis entries automatically fail open, forwarding requests to the upstream provider without client-facing 500 errors.
- **Zero Budget & Provider Usage Overhead**: Semantic cache hits consume $0.00 provider budget and emit zero false provider usage events.
- **Offline ML Evaluation Harness**: Includes an evaluation suite (`evaluation/semantic_cache/`) and benchmark runner to empirically sweep similarity thresholds and measure precision, recall, and false-positive rates.

See [`docs/semantic-cache.md`](docs/semantic-cache.md) for full architectural specifications and [`docs/semantic-cache-benchmarks.md`](docs/semantic-cache-benchmarks.md) for empirical benchmark and evaluation results.

---

## Learned Model Router

Tollgate **Phase 9** introduces an intelligent, cost-aware model routing layer that evaluates prompt structure before calling providers, choosing whether to dispatch to a cheaper model or escalate to a stronger model:

```text
Client Request
      ↓
Authentication & Rate Limit
      ↓
Exact Response Cache Lookup (Phase 7)
      ├── HIT  ──► Return Cached Response ($0.00 cost, 0ms router latency)
      └── MISS ──┐
Semantic Response Cache Lookup (Phase 8)
      ├── HIT  ──► Return Cached Response ($0.00 cost, 0ms router latency)
      └── MISS ──┐
Model Router (Phase 9)
      ├─ Extract 15 Prompt Signals (length, code, SQL, math, turn depth)
      ├─ Classifier Inference: P(cheap_sufficient)
      ├─ Decision: P >= threshold ? cheap_model : strong_model
      └─ Fail-Open Resilience: Falls back safely on any ML/artifact error
      ↓
Atomic Budget Reservation (Phase 5)
      (Estimated and reserved against the selected model tier)
      ↓
Provider Execution (Phase 3)
      ↓
Dual Cache Write (Phase 7 & 8)
      ↓
Asynchronous Usage Event Pipeline (Phase 6)
```

### Key Capabilities
- **42.2% - 42.5% Cost Savings**: Reduces token spend without quality degradation (0.0% false positive rate at operating threshold $\tau = 0.70 - 0.80$).
- **Sub-Millisecond Overhead**: Feature extraction (~0.04ms) and classifier inference (~0.06ms) add $<0.15\text{ms}$ total request latency.
- **Fail-Open Resilience**: If model artifacts are missing or an unhandled exception occurs, the router automatically fails open to the original requested model or a designated fallback.
- **Shadow Mode**: Evaluate routing quality and latency in real production traffic without altering actual model selection.
- **Zero-Overhead Cache Hit Bypass**: Exact and semantic cache hits return immediately without executing feature extraction or ML inference.

See [`docs/model-router.md`](docs/model-router.md) for architecture, configuration settings, and headers, and [`docs/model-router-evaluation.md`](docs/model-router-evaluation.md) for benchmark evaluation, threshold sweeps, and cost-quality tradeoff curves.

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

### Response Cache (Phases 7 & 8)
- `DELETE /api/v1/projects/{project_id}/cache` — Invalidate project cache (O(1) generation counter increment for exact cache, and purges semantic cache entries)
- `GET /api/v1/projects/{project_id}/cache/semantic` — List semantic cache entry metadata for project (entry ID, model, provider, expiration, hit count)

### Dashboard & Analytics (Phase 10)
- `GET /api/v1/dashboard/overview` — High-level telemetry summary KPIs (requests, tokens, cost, cache, router)
- `GET /api/v1/dashboard/usage` — Time-series aggregation buckets for requests, tokens, and cost
- `GET /api/v1/dashboard/costs` — Cost distribution across models, providers, and projects
- `GET /api/v1/dashboard/budgets` — Phase 5 atomic budget status, spent microdollars, utilization
- `GET /api/v1/dashboard/models` — Model throughput, token consumption, latency, and error rates
- `GET /api/v1/dashboard/providers` — Upstream provider reliability, retries, fallbacks, and latency
- `GET /api/v1/dashboard/cache` — Exact vs semantic cache performance, hit rates, and estimated cost avoided
- `GET /api/v1/dashboard/router` — Production routing distribution vs offline benchmark evaluation reports
- `GET /api/v1/dashboard/requests` — Server-side paginated request explorer with filters and sorting
- `GET /api/v1/dashboard/requests/{id}` — Safe request metadata and telemetry inspection modal
- `POST /api/v1/auth/login` — Email/password credential verification returning active token
- `GET /api/v1/auth/me` — Current authenticated user profile, tenant identity, and projects

See [`docs/dashboard.md`](docs/dashboard.md) for full dashboard architecture, security guarantees, and RBAC policies.

---

## Quick Start (Docker Compose)

Launch the complete stack (FastAPI + PostgreSQL with pgvector + Redis + Worker + React Dashboard) with a single command:

```bash
docker compose up --build
```

---

## Local Development & Testing

```bash
# Run complete test suite (unit + integration + OpenAI SDK compatibility)
pytest

# Run benchmark smoke suite (fast PR validation)
python benchmarks/scripts/run_benchmarks.py --mode smoke

# Run full benchmark suite (all 12 scenarios with full concurrency ladders)
python benchmarks/scripts/run_benchmarks.py --mode full

# Run automated regression detection
python benchmarks/scripts/detect_regression.py --baseline benchmarks/results --current benchmarks/results --threshold-percent 10.0
```

See [`docs/benchmarking.md`](docs/benchmarking.md), [`docs/benchmark-methodology.md`](docs/benchmark-methodology.md), and [`docs/benchmark-results.md`](docs/benchmark-results.md) for full benchmarking methodology and actual run results.

---

## Production Deployment & Operations (Phase 15)

### Architecture
Tollgate deploys as a modular monolith via Docker Compose behind an NGINX reverse proxy with HTTP/2 and SSE streaming support. Public traffic is isolated on `tollgate-frontend`, while PostgreSQL, Redis, Worker, and Observability services run securely within `tollgate-backend`.

### Deployment Environments

| Environment | Compose File | Purpose |
|-------------|-------------|--------|
| Development | `docker-compose.yml` | Local development with relaxed defaults |
| Staging | `docker-compose.staging.yml` | Pre-production testing, mirrors prod topology |
| Production | `docker-compose.prod.yml` | Hardened, no host port exposure for data stores |

### Health & Version Endpoints
* **Liveness**: `GET /health/live` — Instant process check (`{"status": "alive"}`).
* **Readiness**: `GET /health/ready` — Verifies PostgreSQL and Redis health (`200 OK` or `503 Unavailable`).
* **Version**: `GET /health/version` — Returns immutable Git SHA, semantic version, and environment.

### Database Migrations
```bash
python -m alembic upgrade head
```

### Automated Deployment
```bash
cp .env.example .env        # Configure production secrets
./scripts/deploy.sh         # Build, migrate, deploy, verify
```

### Post-Deployment Validation
```bash
./scripts/smoke_test.sh          # Endpoint health & auth checks
./scripts/validate_deployment.sh # Container security & network checks
./scripts/security_validate.sh   # Security posture validation
```

### Rollback & Recovery
```bash
./scripts/rollback.sh <known_good_git_sha>   # Image-based rollback
./scripts/backup_postgres.sh                  # Create database backup
./scripts/restore_postgres.sh backups/<file>  # Restore from backup
```

### Failure Testing
```bash
./scripts/failure_test.sh   # Redis/Postgres/Worker failure injection
```

### CI/CD Pipeline
The GitHub Actions CI pipeline (`.github/workflows/ci.yml`) runs:
1. **Dependency audit** and secret scanning
2. **Lint**, type checking, and full test suite
3. **Docker image builds** for gateway, worker, and dashboard
4. **Staging deployment** with automated smoke tests (on `main` and `feat/*`)

### Documentation
* [`docs/deployment.md`](docs/deployment.md) — Production architecture and setup
* [`docs/deployment-checklist.md`](docs/deployment-checklist.md) — Pre/post-deployment checklist
* [`docs/production-config.md`](docs/production-config.md) — Environment variable reference
* [`docs/rollback.md`](docs/rollback.md) — Rollback strategy
* [`docs/rollback-drill.md`](docs/rollback-drill.md) — Rollback drill runbook
* [`docs/backup-restore.md`](docs/backup-restore.md) — Backup/restore procedures
* [`docs/restore-drill.md`](docs/restore-drill.md) — Restore drill runbook
* [`docs/security.md`](docs/security.md) — Security audit and known limitations
