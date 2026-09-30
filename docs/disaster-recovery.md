# Tollgate Disaster Recovery & High Availability Procedures

## 1. Overview & Disaster Scenarios

Disaster Recovery (DR) defines the actionable runbooks, technical tools, and procedures required to restore the Tollgate LLM Gateway following major component failures, data corruption, or total host destruction.

### Disaster Categories
1. **Catastrophic Host Destruction**: Complete loss of the cloud virtual machine or hardware host.
2. **PostgreSQL Database Failure / Corruption**: Unrecoverable corruption of primary database files or storage volume.
3. **Redis Crash & Cache Invalidation**: Unexpected Redis termination, memory exhaustion, or AOF/RDB corruption.
4. **Worker Failure & Stream Backlog**: All worker processes fail, causing Redis Streams unacknowledged message backlog.
5. **Upstream LLM Provider Outage**: Complete or intermittent failure of primary upstream provider (e.g., OpenAI or Anthropic 5xx errors).
6. **Disk Saturation (100% Full)**: File system fills completely, blocking database WAL writes and container logging.

---

## 2. PostgreSQL Disaster Recovery Architecture

### Backup Typology & Guarantees
| Backup Type | Frequency | Tooling | Retention | RPO Guarantee | Target Storage |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Logical Backups** | Hourly | `pg_dump -Fc` | 7 Days | < 1 hour | Encrypted S3 / Cloud Bucket |
| **Nightly Snapshots** | Daily (02:00 UTC) | `pg_dump -Fc` | 30 Days | < 24 hours | Encrypted S3 / Cloud Bucket |
| **Physical WAL Archiving** | Continuous (optional) | `pg_receivewal` | 3 Days | < 5 minutes | Dedicated NFS / Object Storage |

> [!NOTE]
> In the single-host standard deployment model, **Hourly Logical Backups (`pg_dump`)** are the active baseline mechanism. True Point-In-Time Recovery (PITR) requires continuous WAL shipping to an external object store. Do not claim PITR capability unless `archive_mode = on` and WAL shipping are configured to an external bucket.

### Backup Integrity Verification
Every automated backup must undergo cryptographic and structural validation:
```bash
# 1. Compute and verify SHA256 checksum
sha256sum /var/backups/tollgate/postgres_latest.dump > /var/backups/tollgate/postgres_latest.dump.sha256
sha256sum -c /var/backups/tollgate/postgres_latest.dump.sha256

# 2. Verify archive table of contents without restoring
pg_restore -l /var/backups/tollgate/postgres_latest.dump > /dev/null
echo "Exit code: $? (0 = valid pg_dump archive)"
```

### PostgreSQL Recovery Runbook (Step-by-Step)
```bash
# Step 1: Drain client traffic (NGINX returns 503)
docker compose -f docker-compose.prod.yml stop gateway worker

# Step 2: Stop and reset corrupted database container
docker compose -f docker-compose.prod.yml stop postgres
docker compose -f docker-compose.prod.yml rm -f postgres
docker volume rm tollgate_postgres_data
docker volume create tollgate_postgres_data

# Step 3: Start fresh PostgreSQL container
docker compose -f docker-compose.prod.yml up -d postgres
echo "Waiting for postgres readiness..."
docker compose -f docker-compose.prod.yml exec postgres pg_isready -U tollgate -d tollgate_db

# Step 4: Restore database from verified backup
docker compose -f docker-compose.prod.yml exec -T postgres pg_restore \
    -U tollgate \
    -d tollgate_db \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges < /var/backups/tollgate/postgres_latest.dump

# Step 5: Verify table integrity and record counts
docker compose -f docker-compose.prod.yml exec postgres psql -U tollgate -d tollgate_db -c \
    "SELECT 'tenants' as table, count(*) FROM tenants UNION ALL SELECT 'api_keys', count(*) FROM api_keys UNION ALL SELECT 'usage_events', count(*) FROM usage_events;"

# Step 6: Start API and Worker services
docker compose -f docker-compose.prod.yml up -d gateway worker
bash scripts/smoke_test.sh
```

---

## 3. Redis Disaster Recovery Strategy

Redis stores three distinct classifications of data with different durability requirements:
1. **Disposable / Ephemeral**: Exact LLM response cache, rate-limiting token buckets.
2. **Operational**: Active circuit breaker counters.
3. **Important Buffer**: Unpersisted usage stream events (`tg:usage:events`).

### Redis Durability Configuration
Production Redis runs with Append-Only File (AOF) persistence enabled:
```text
appendonly yes
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
maxmemory 2gb
maxmemory-policy volatile-lru
```

### Redis Recovery Scenarios
- **Clean Restart**: Redis automatically reloads `/data/appendonlydir` or `dump.rdb` on startup.
- **Corrupted AOF File**:
  ```bash
  # Repair corrupted AOF
  docker compose -f docker-compose.prod.yml run --rm redis redis-check-aof --fix /data/appendonlydir/appendonly.aof.*
  ```
- **Total Redis Data Loss**:
  1. Redis starts completely empty.
  2. Gateway API initializes and discovers empty cache (safe: all requests hit upstream LLMs).
  3. Token buckets reset to initial burst limit (safe: allows configured QPS).
  4. Workers initialize consumer group with `xgroup_create(..., id="0", mkstream=True)`.
  5. API and inference path continue with zero fatal errors.

---

## 4. Usage Stream & Worker Crash Recovery

If worker processes crash while usage events are in flight, the Redis Stream ensures zero data loss:

```text
Step 1: Gateway publishes event via XADD -> message assigned Stream ID (e.g. 1711800000000-0)
Step 2: Worker 1 reads event via XREADGROUP -> message enters Pending Entries List (PEL)
Step 3: Worker 1 crashes before DB commit and XACK
Step 4: Message remains pending in stream. Idle time accumulates.
Step 5: Worker 2 runs XAUTOCLAIM (idle threshold > 60s) -> message reassigned to Worker 2
Step 6: Worker 2 persists event to PostgreSQL with ON CONFLICT (event_id) DO NOTHING
Step 7: Worker 2 calls XACK -> message cleared from PEL
```

### Verification Command:
```bash
# Check stream length and pending messages in production
docker compose -f docker-compose.prod.yml exec redis redis-cli -a "${REDIS_PASSWORD}" \
    XINFO GROUPS tg:usage:events
```

---

## 5. Budget Recovery & Leak Prevention

Budget tracking uses a **two-phase reservation and settlement** protocol:
1. **Pre-Request Phase**: A temporary reservation is created in Redis (`tg:budget:reserve:<tenant_id>:<reservation_id>`) with a 60-second TTL.
2. **Post-Request Phase**: Gateway calls `BUDGET_SETTLE_LUA` to delete the reservation and atomically increment `tg:budget:spend:<tenant_id>`.

### Crash Scenarios:
- **Crash between Reservation & Provider Call**: The upstream provider is never called. After 60 seconds, the Redis reservation key automatically expires and vanishes. The tenant balance is fully restored with zero manual intervention.
- **Crash during Provider Call**: The reservation TTL expires. If the provider call actually finished, the usage worker's subsequent event persistence reconciles the actual spend into the PostgreSQL permanent ledger.
- **Master Balance Synchronization**: If Redis loses state, the master budget balances are re-initialized directly from PostgreSQL rollups:
  ```sql
  SELECT tenant_id, SUM(actual_cost) as total_cost 
  FROM usage_daily_rollups 
  WHERE date >= CURRENT_DATE 
  GROUP BY tenant_id;
  ```

---

## 6. Upstream Provider Outage & Cascading Failure Isolation

When OpenAI, Anthropic, or external providers fail (5xx responses, timeouts, connection resets):
1. **Circuit Breaker Engagement**:
   - Each `provider:model` pair maintains a sliding window of recent requests.
   - If failures exceed threshold (`TOLLGATE_CIRCUIT_FAILURE_THRESHOLD=5` within `TOLLGATE_CIRCUIT_WINDOW_SECONDS=30`), the circuit state switches to `OPEN`.
   - All subsequent requests to that model immediately fail-fast (raising HTTP 503) without making outbound HTTP calls, preventing connection pool starvation.
2. **Automatic Fallback Routing**:
   - If a fallback model is configured (`router_fallback_model`), the gateway automatically routes requests to the secondary provider.
3. **Probe & Self-Healing**:
   - After recovery timeout (`TOLLGATE_CIRCUIT_RECOVERY_TIMEOUT_SECONDS=30`), the circuit enters `HALF_OPEN`.
   - A single probe request is permitted through. If successful, the circuit resets to `CLOSED`.

---

## 7. Disk Exhaustion Emergency Remediation

If host disk usage reaches 100%:
```bash
# 1. Identify disk consumers
df -h
du -sh /var/lib/docker/* | sort -h

# 2. Prune unused docker images and stopped containers (NON-DESTRUCTIVE to volumes)
docker system prune -f

# 3. Truncate oversized JSON log files without stopping containers
truncate -s 0 /var/lib/docker/containers/*/*-json.log

# 4. Clean old archived backups (>7 days old)
find /var/backups/tollgate -type f -mtime +7 -name "*.dump" -delete

# 5. NEVER run 'rm -rf' on postgres or redis data directories!
```

---

## 8. Total Host Destruction Reconstitution Guide

If the host server is completely destroyed, follow this rapid cold-reconstitution procedure:

1. **Provision New Host**: Provision a Linux VM (Ubuntu 22.04 / 24.04 LTS) with Docker and Docker Compose installed.
2. **Clone Repository & Checkout Release**:
   ```bash
   git clone https://github.com/mayanksingh2745/Tollgate-a-multi-tenant-LLM-gateway-with-budgets-semantic-caching-and-cost-quality-routing.git /app/tollgate
   cd /app/tollgate
   git checkout main
   ```
3. **Configure Environment Secrets**:
   ```bash
   cp .env.example .env
   # Populate POSTGRES_PASSWORD, REDIS_PASSWORD, METRICS_TOKEN, PROVIDER_KEYS
   ```
4. **Retrieve Latest Backups**:
   ```bash
   aws s3 cp s3://tollgate-backups/latest.dump /var/backups/tollgate/postgres_latest.dump
   ```
5. **Start Core Services & Restore Database**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d postgres redis
   docker compose -f docker-compose.prod.yml exec -T postgres pg_restore -U tollgate -d tollgate_db < /var/backups/tollgate/postgres_latest.dump
   ```
6. **Launch Full Redundant Stack**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```
7. **Run Automated Validation**:
   ```bash
   bash scripts/smoke_test.sh
   ```
   **Total Expected RTO: < 25 minutes.**
