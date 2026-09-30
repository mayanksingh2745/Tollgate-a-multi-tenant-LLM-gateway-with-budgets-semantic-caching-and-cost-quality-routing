# Tollgate High Availability & Failure-Domain Architecture

## 1. System Topology & Failure Domains

The Tollgate gateway sits directly in the data plane between client applications and external upstream LLM providers (OpenAI, Anthropic, Mock). To analyze its resilience, we evaluate the interaction graph across each layer:

```text
                  ┌────────────────────────┐
                  │   Client Applications  │
                  └───────────┬────────────┘
                              │ HTTP / TLS (Port 80/443)
                              ▼
                  ┌────────────────────────┐
                  │  Reverse Proxy (NGINX) │
                  └───────────┬────────────┘
                              │ Load Balancing & Failover
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
┌───────────────────────┐           ┌───────────────────────┐
│  Gateway API Replica 1 │           │  Gateway API Replica 2 │
│      (Port 8000)      │           │      (Port 8001)      │
└───────────┬───────────┘           └───────────┬───────────┘
            │                                   │
            ├───────────────┬───────────────────┤
            │               │                   │
            ▼               ▼                   ▼
     ┌────────────┐  ┌─────────────┐    ┌───────────────┐
     │ PostgreSQL │  │ Redis Cache │    │ External LLMs │
     │  (Primary) │  │  & Streams  │    │  (Providers)  │
     └────────────┘  └──────┬──────┘    └───────────────┘
                            │ Usage Stream (XADD)
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌───────────────────────┐       ┌───────────────────────┐
│ Usage Worker Consumer │       │ Usage Worker Consumer │
│       Replica 1       │       │       Replica 2       │
└───────────┬───────────┘       └───────────┬───────────┘
            │                               │
            └───────────────┬───────────────┘
                            ▼
                     ┌────────────┐
                     │ PostgreSQL │
                     │  (Persist) │
                     └────────────┘
```

---

## 2. Failure Domain Analysis

| Failure Domain | Primary Impact | Detection Mechanism | Containment / Mitigation | Recovery Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **API Process Failure** | Individual worker thread/process terminates | Uvicorn worker crash / exit code 1; OS signal | Supervisor / Docker restart policy (`restart: always`) | Instant process respawn (<2s); upstream proxy routes to peer replica |
| **API Container Failure** | Container stops due to OOM or panic | Docker daemon healthcheck (`curl /healthz`) fails | Multi-replica API topology; NGINX `proxy_next_upstream` | Container auto-restart; zero traffic routed until `/health/ready` passes |
| **Host Failure (Single VM)** | **TOTAL SYSTEM OUTAGE** | External uptime probe / cloud health check | None within single host; VM restart | Cloud host reboot or automated cold disaster recovery from off-site backups |
| **PostgreSQL Outage** | Auth, key verification, and persistent rollups fail | `check_db_health()` (`SELECT 1`) fails in `/health/ready` | Readiness probe fails; gateway returns HTTP 503; rejects unsafe state changes | Database service restart; connection pool auto-reconnects |
| **Redis Outage** | Distributed rate limiting, cache, & usage queue unavailable | `check_redis_health()` fails; Redis connection exceptions | Cache fails open (bypassed); rate limiter adheres to fail-open/closed policy | Redis container restart; AOF/RDB reload; connection pool reconnects |
| **Worker Process Failure** | Usage stream processing pauses | Consumer heartbeat stops; stream lag metric spikes | Stream messages remain buffered in Redis; unacknowledged messages idle | Remaining worker auto-claims stale messages after idle timeout via `XAUTOCLAIM` |
| **Upstream Provider Failure** | Latency spikes, 502/503/504 errors returned to client | Failure classifier flags HTTP 5xx / timeouts / connection errors | Circuit breaker opens (trips); fast-fails further requests without upstream calls | Fallback provider invoked; circuit breaker enters `HALF_OPEN` and probes recovery |
| **Partial Provider Failure** | Intermittent errors or degraded performance | Sliding window error rate exceeds threshold | Retries with exponential backoff & jitter; circuit breaker trips if persistent | Automatic failover to secondary configured provider |
| **Network Partition (Split)** | Gateway isolated from DB, Redis, or providers | Connection timeouts; health check failures | Readiness drops; traffic shedding; circuits trip | TCP connection retry policies with exponential backoff |
| **Disk Exhaustion** | PostgreSQL halts writes; Docker fails container creation | Host monitoring alerts (`node_exporter`, disk >85%) | Log rotation limits (`max-size: 10m`, `max-file: 5`); vacuuming | Disk expansion, pruning old docker layers, archiving historical backups |
| **Deployment Failure** | Broken build or syntax regression deployed | Automated smoke tests in CI/CD pipeline fail | Deployment halted before traffic promotion; container rollback | Immediate rollback to previous image tag via `scripts/rollback.sh` |
| **Observability Outage** | Loss of Jaeger traces or Prometheus metrics | Metrics scrape failure; OTel exporter timeout | OTel export timeout set to non-blocking; metrics buffered locally in memory | Telemetry failure NEVER degrades client traffic; metrics resume when exporter recovers |

---

## 3. The Honesty Assessment: What Is and Is NOT High Availability

> [!CAUTION]
> **CRITICAL ARCHITECTURAL HONESTY NOTICE**
> The current production deployment architecture uses a **single virtual machine / single container host**. It is resilient, but it is **NOT** a distributed high-availability (HA) architecture.

### What is Achieved (Process & Component Resilience):
1. **Container & Process Resilience**: If any individual application component (Gateway API, Background Worker, NGINX) panics or experiences an unhandled exception, Docker restart policies and multi-instance redundancy restore service immediately.
2. **Graceful Multi-Replica Failover**: NGINX load balances between multiple local API instances (`gateway-1` and `gateway-2`) with health check gating (`proxy_next_upstream`), guaranteeing that restarting an API instance produces zero downtime for clients.
3. **Queue & Message Durability**: The Redis Streams usage queue decouples the high-throughput inference path from relational persistence. If the worker crashes or PostgreSQL is temporarily unreachable, events remain buffered in Redis and are reclaimed automatically by peer workers.
4. **Idempotent Data Settlement**: Both usage event ingestion and budget settlement enforce idempotency keys, guaranteeing that network retries or worker restarts never cause duplicate billing or double-counted tokens.
5. **Durable Disaster Recovery**: Scheduled automated database and cache backups allow reconstituting the full system state onto a fresh host within predefined RTO/RPO limits.

### What is NOT Achieved (Single-Host Limitations):
1. **Host-Level High Availability**: If the physical server or cloud hypervisor hosting the VM fails, the entire Tollgate gateway is unavailable until the VM is restarted or a new host is provisioned.
2. **Multi-Zone Redundancy**: The database and cache run as single instances without synchronous cross-AZ replication.
3. **Multi-Region Redundancy**: Tollgate does not feature active-active multi-region database replication or GeoDNS automatic failover.
4. **Transparent TCP Session Migration**: Active Server-Sent Events (SSE) streaming connections interrupted by a process restart will be terminated and must be reconnected by the client application.

---

## 4. Multi-Instance API Redundancy Model

To achieve application-level redundancy on the host, the Gateway API is designed to operate in multi-replica active-active mode behind NGINX:

```text
       [ NGINX Reverse Proxy (Port 80/443) ]
          │                          │
          ▼                          ▼
 [ gateway-1:8000 ]           [ gateway-2:8000 ]
```

### Upstream Proxy Configuration:
```nginx
upstream gateway_upstream {
    least_conn;
    server gateway-1:8000 max_fails=3 fail_timeout=10s;
    server gateway-2:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}
```

### Failover Directives:
```nginx
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 2;
proxy_next_upstream_timeout 5s;
```

When `gateway-1` is down or unready (returning 503 from `/health/ready`), NGINX immediately directs pending and new connections to `gateway-2`. Active health checks and connection timeouts prevent client requests from stalling.
