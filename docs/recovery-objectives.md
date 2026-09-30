# Tollgate Recovery Objectives & Data Classification

## 1. Recovery Time Objectives (RTO) & Recovery Point Objectives (RPO)

Recovery objectives define the strict boundaries of permissible downtime and data loss in the event of component, service, or host failure.

### Definitions
- **Recovery Time Objective (RTO)**: The maximum acceptable elapsed duration between the declaration of an incident/disaster and the complete restoration of service.
- **Recovery Point Objective (RPO)**: The maximum acceptable age of data that can be lost when recovery is completed (the time window of data loss).

---

## 2. Component-by-Component Objectives

| Component / Subsystem | Target RTO | Target RPO | Failure Scenario | Recovery Mechanism & Real-World Limitations |
| :--- | :---: | :---: | :--- | :--- |
| **API Availability (Process/Container)** | **< 5 seconds** | **0** | Gateway container crash / OOM | Transparent failover to peer replica via NGINX upstream; Docker daemon auto-restart. Zero data loss. |
| **API Availability (Host Outage)** | **< 30 minutes** | **< 1 hour** | Complete VM destruction | Cold reconstitution of host via Ansible/Docker Compose + database backup restore. |
| **PostgreSQL Tenant & Identity Data** | **< 15 minutes** | **< 1 hour** | Database corruption or storage loss | Restore from latest encrypted logical/physical database backup. |
| **PostgreSQL Usage Events & Rollups** | **< 15 minutes** | **< 5 minutes** | Database failure while Redis stream intact | Redis Stream buffers incoming usage events. When DB returns, workers replay from stream. |
| **Budget Accounting & Reservations** | **< 30 seconds** | **< 60 seconds** | Redis restart or crash | In-flight reservations expire via TTL (<60s). Balance restored from PostgreSQL master records. |
| **Dashboard Analytics & Metrics** | **< 1 hour** | **< 1 hour** | Database rollup table corruption | Rollup tables can be completely reconstructed from raw `usage_events` via batch SQL script. |
| **Exact Response Cache (Redis)** | **< 1 minute** | **N/A (Disposable)** | Redis flush / node eviction | Ephemeral cache is disposable. Gateway falls back to provider execution and repopulates cache. |
| **Semantic Response Cache (pgvector)** | **< 30 minutes** | **< 1 hour** | PostgreSQL data loss | Reconstituted from database backup; entries not critical for operational proxy routing. |
| **Distributed Rate Limiting State** | **< 30 seconds** | **N/A (Disposable)** | Redis flush / restart | Token bucket counters reset to full burst capacity. Temporary burst allowed for <10s window. |
| **OpenTelemetry Traces & Prometheus** | **< 30 minutes** | **< 5 minutes** | Monitoring container crash | In-memory scraping targets buffer metrics locally; transient collector loss causes zero proxy impact. |

---

## 3. Data Classification Matrix

Tollgate partitions its data across storage engines based on criticality, durability requirements, and recoverability:

| Data Category | Primary Store | Classification | Durability Strategy | Recoverability Mechanism |
| :--- | :--- | :---: | :--- | :--- |
| **Tenants, Projects, Users** | PostgreSQL | **CRITICAL** | WAL + Automated Backups | Logical dump (`pg_dump`) & point-in-time restore |
| **API Keys & Argon2 Hashes** | PostgreSQL | **CRITICAL** | WAL + Automated Backups | Restored from backup; immutable once created |
| **Budget Policies & Limits** | PostgreSQL | **CRITICAL** | WAL + Automated Backups | Master limits in DB; synced to Redis Lua counters |
| **Usage Events (Raw Audit)** | PostgreSQL | **CRITICAL** | WAL + Backups + Redis Stream | Replayable from Redis Stream if DB down; permanent DB record |
| **Daily & Monthly Rollups** | PostgreSQL | **IMPORTANT** | Atomic Upsert with raw events | Rebuildable by aggregating `usage_events` table |
| **Usage Stream (In-flight Queue)** | Redis Streams | **IMPORTANT** | AOF (`appendonly yes`) + In-memory | Retained in Redis until explicitly ACKed by worker |
| **Exact Request Cache** | Redis | **DISPOSABLE** | In-memory + LRU Eviction | Automatically repopulated by cache-miss upstream calls |
| **Semantic Cache Embeddings** | PostgreSQL | **IMPORTANT** | pgvector HNSW Index + WAL | Rebuildable from provider embeddings or restored from DB backup |
| **Rate Limit Token Buckets** | Redis | **DISPOSABLE** | In-memory with TTL | Ephemeral; auto-initialized on first client request |
| **Active Circuit Breaker State** | Gateway Memory / Redis | **OPERATIONAL** | In-memory sliding window | Auto-probed; resets to CLOSED on restart, trips if provider fails |
| **Prometheus Metrics & Traces** | Local Memory / Jaeger | **OPERATIONAL** | Prometheus TSDB / Jaeger Storage | Non-critical telemetry; loss does not affect customer traffic |

---

## 4. Failure Priority & Recovery Sequence

When bringing up a degraded or recovered Tollgate deployment, services must be sequenced in strict order of dependency:

```text
Priority 0: Foundational Storage & Identity
  ├── 1. PostgreSQL (Database engine healthy & responsive)
  └── 2. Redis (Cache, rate limiting & stream queues online)

Priority 1: Core Data Plane & Authentication
  ├── 3. Gateway API Replicas (gateway-1, gateway-2 behind NGINX)
  ├── 4. Reverse Proxy (NGINX routing traffic & enforcing TLS/rate limits)
  └── 5. Authentication & Budget Pre-flight Verification

Priority 2: Asynchronous Pipelines & Settlement
  ├── 6. Usage Worker Consumers (Stream consumption & rollup processing)
  └── 7. Provider Circuit Breakers & Fallback Routing verification

Priority 3: Observability & Disposable Acceleration
  ├── 8. Prometheus & OpenTelemetry Collector
  ├── 9. Grafana Dashboards & Analytics UI
  └── 10. Cache Warm-up (Exact & Semantic caches)
```

### Rationale
- **Why PostgreSQL first**: The Gateway cannot start or serve authenticated requests without database access to verify API keys and tenant statuses.
- **Why Redis before API**: Budget reservations, rate limiting, and exact response caching require Redis connectivity. If Redis is unavailable, the API operates in degraded or fail-safe mode.
- **Why Workers after API**: The API can accept inference traffic and buffer events into Redis Streams even if workers are delayed in starting. Workers can catch up asynchronously with zero data loss.
- **Why Observability last**: Telemetry must never block or delay the recovery of user-facing production traffic.
