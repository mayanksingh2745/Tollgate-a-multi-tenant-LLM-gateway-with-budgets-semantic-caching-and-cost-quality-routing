# Tollgate Resilience Testing & Failure Injection Methodology

## 1. Overview & Test Objectives

The resilience test harness verifies that the Tollgate LLM Gateway gracefully survives component failures, network anomalies, provider degradation, and resource constraints without corrupting financial balances, losing usage audit trails, or hanging client requests.

---

## 2. Test Suite Architecture

All automated failure tests reside in:
`tests/resilience/`

| Test Module | Failure Scenario | Target Subsystem | Key Verification |
| :--- | :--- | :--- | :--- |
| **`test_api_multi_instance.py`** | Multi-instance concurrent requests | API Replicas behind LB | Rate limit state synchronized; budget reservations consistent; zero split-brain |
| **`test_worker_failover_and_reclaim.py`** | Worker crash during stream processing | Redis Streams & Workers | Stale messages reclaimed via `XAUTOCLAIM`; idempotency prevents double-counting |
| **`test_budget_and_usage_recovery.py`** | Gateway crash after reservation | Budget & Usage Engine | TTL automatically releases orphaned reservations; duplicate events ignored |
| **`test_infrastructure_failures.py`** | PostgreSQL & Redis outage | DB & Cache Layer | `/health/ready` returns 503; API fails safe; auto-reconnects upon restoration |
| **`test_provider_failures_and_streaming.py`**| Upstream 10%/30%/50%/100% 5xx errors | Circuit Breakers & Router | Retries with jitter; circuit trips; fallback routes; streaming aborts cleanly |
| **`test_observability_isolation.py`** | Metrics & OTel backend down | Prometheus & Tracing | Telemetry failure NEVER degrades or slows client inference requests |
| **`test_chaos_recovery.py`** | Catastrophic cache loss, connection storm & provider chaos | Cache, Circuit & Concurrency | Cache fail-open & repopulate, 50-concurrency stability, zero double-counting under worker crash |
| **`test_multi_instance_tenant_isolation.py`** | Cross-instance multi-tenant access attempts | Auth, Rates, Budgets & Cache | Zero cross-tenant data leakage across separate gateway replicas |

---

## 3. Simulated Failure Injection Details

### A. Multi-Instance API Synchronization
- **Injection**: Spin up two isolated FastAPI gateway instances sharing the exact same PostgreSQL and Redis instances.
- **Assertion**: Concurrent requests distributed across Instance 1 and Instance 2 accurately exhaust the global Redis token bucket and deduct from the shared budget without race conditions.

### B. Worker Crash & Pending Stream Reclaim
- **Injection**: Worker A reads a message from `tg:usage:events` via consumer group `tg-usage-workers`. Worker A's process aborts before executing `XACK`.
- **Assertion**: The message remains pending in Redis Streams PEL. Worker B invokes `reclaim_stale_messages()`. Worker B successfully claims the message, persists it to the database with `ON CONFLICT DO NOTHING`, and sends `XACK`. The database records exactly 1 event and 1 rollup increment.

### C. Budget Reservation Crash & TTL Eviction
- **Injection**: Gateway creates an active budget reservation for 5,000 micro-cents with a short TTL (1 second). The simulation halts without calling `settle` or `release`.
- **Assertion**: After TTL expires, the reservation evaporates from Redis. The tenant's available spending balance returns to 100% of its pre-reservation capacity.

### D. Upstream Provider Intermittent Degradation
- **Injection**: A mock upstream provider fails with configurable failure rates:
  - 10% Failure Rate (Occasional transient 500 error)
  - 30% Failure Rate (Intermittent flakiness)
  - 50% Failure Rate (Degraded upstream)
  - 100% Failure Rate (Complete provider outage)
- **Assertion**:
  - At low failure rates, the retry mechanism handles transient failures transparently.
  - At sustained high failure rates, the circuit breaker opens, triggering instant fallback to the secondary provider.

### E. Streaming Interruption & Client Disconnection
- **Injection**: A streaming request starts receiving tokens via Server-Sent Events. Upstream connection is abruptly terminated midway through chunk delivery.
- **Assertion**:
  - The gateway stops streaming, cancels upstream sockets, and records the error.
  - The gateway settles the budget based on tokens received prior to disconnection.
  - Zero hanging socket connections remain.

### F. Observability Failure Isolation
- **Injection**: OpenTelemetry OTLP HTTP exporter endpoint points to an unreachable host (`http://127.0.0.1:9999`) with simulated 5-second socket delays. Prometheus client metrics fail with simulated exceptions.
- **Assertion**: The gateway continues processing LLM completions with <5ms overhead. Client latency is completely isolated from telemetry network timeouts.
