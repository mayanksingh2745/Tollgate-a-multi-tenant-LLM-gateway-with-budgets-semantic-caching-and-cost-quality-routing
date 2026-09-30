# Tollgate Observability Alerting Rules & Response Procedures

This document defines production alert rules for Prometheus Alertmanager, covering infrastructure availability, component degradation, queue backlogs, provider failures, and disaster recovery signals.

---

## Alerting Philosophy
1. **Actionable Alerts Only**: Every alert corresponds to an explicit runbook in [`docs/operations-runbook.md`](operations-runbook.md) or [`docs/disaster-recovery.md`](disaster-recovery.md).
2. **Bounded Cardinality**: Alert expressions use bounded metric labels only.
3. **Multi-Replica Aware**: Distinct alert thresholds for single-replica degradation versus complete subsystem outage.

---

## 1. High Availability & Subsystem Alerts

### `TollgateAPIUnavailable` (P0 — Immediate Page)
- **Expression**: `sum(up{job="tollgate-api"}) == 0`
- **Duration**: `30s`
- **Description**: Zero API gateway instances are reachable by the Prometheus scraper or reverse proxy.
- **Impact**: Complete inability to handle chat completion, authentication, or management requests.
- **Runbook**: [`docs/operations-runbook.md#16-api-host-failure--cold-reconstitution`](operations-runbook.md#16-api-host-failure--cold-reconstitution).

### `TollgateAPISingleReplicaDegraded` (P1 — Urgent)
- **Expression**: `count(up{job="tollgate-api"} == 1) < 2`
- **Duration**: `1m`
- **Description**: Only one API replica is healthy out of the configured multi-replica pool. Traffic is successfully failing over, but redundancy is lost.
- **Impact**: NGINX `proxy_next_upstream` absorbs traffic, but single point of failure risk is active.
- **Runbook**: Check failing container logs: `docker logs tollgate-gateway-1`.

### `TollgatePostgresUnavailable` (P0 — Immediate Page)
- **Expression**: `tollgate_infrastructure_postgres_healthy == 0`
- **Duration**: `30s`
- **Description**: Gateway health checks cannot ping or acquire connections from PostgreSQL.
- **Impact**: API readiness probes transition to HTTP 503; proxy sheds traffic; rate limiting and cached reads continue, but mutations fail.
- **Runbook**: [`docs/operations-runbook.md#17-postgresql-complete-outage--cold-restore`](operations-runbook.md#17-postgresql-complete-outage--cold-restore) or execute `bash scripts/recover_postgres.sh`.

### `TollgateRedisUnavailable` (P0 — Immediate Page)
- **Expression**: `tollgate_infrastructure_redis_healthy == 0`
- **Duration**: `30s`
- **Description**: Redis is unreachable or unresponsive to PING commands.
- **Impact**: Distributed rate limiting falls back to configured mode (fail-open or fail-closed); response caching bypassed; usage stream publishing blocked.
- **Runbook**: [`docs/operations-runbook.md#18-redis-crash--cache-recovery`](operations-runbook.md#18-redis-crash--cache-recovery) or execute `bash scripts/recover_redis.sh`.

---

## 2. Pipeline & Worker Alerts

### `TollgateWorkerBacklogIncreasing` (P1 — Urgent)
- **Expression**: `tollgate_usage_queue_pending_messages{stream="tg:usage:events"} > 5000`
- **Duration**: `5m`
- **Description**: Unacknowledged pending messages in the Redis Stream consumer group exceed 5,000 items and are not declining.
- **Impact**: Usage rollups and daily spend updates lag behind real-time.
- **Runbook**: [`docs/operations-runbook.md#19-worker-crash--pending-event-reclamation`](operations-runbook.md#19-worker-crash--pending-event-reclamation) or execute `bash scripts/recover_worker.sh`.

### `TollgateDeadLetterQueueGrowing` (P1 — Urgent)
- **Expression**: `increase(tollgate_usage_dead_letter_queue_messages[15m]) > 5`
- **Duration**: `5m`
- **Description**: Poison-pill or permanently unparsable events are arriving in `tg:usage:dead_letter`.
- **Impact**: Potential dropped usage events requiring manual ledger reconciliation.
- **Runbook**: Inspect DLQ messages: `docker exec tollgate-redis redis-cli XRANGE tg:usage:dead_letter - + COUNT 10`.

---

## 3. Reliability & Provider Alerts

### `TollgateProviderOutage` (P1 — Urgent)
- **Expression**: `sum by (provider) (rate(tollgate_provider_errors_total{status_class="5xx"}[5m])) / sum by (provider) (rate(tollgate_provider_requests_total[5m])) > 0.5`
- **Duration**: `2m`
- **Description**: Upstream provider error rate exceeds 50% over a 5-minute rolling window.
- **Impact**: Triggers provider fallback chains; elevated latency during retry sequence.
- **Runbook**: Verify status page of upstream provider (OpenAI, Anthropic). Verify fallback provider health.

### `TollgateCircuitPermanentlyOpen` (P1 — Urgent)
- **Expression**: `tollgate_circuit_state == 1`
- **Duration**: `15m`
- **Description**: Circuit breaker for a provider+model pair has stayed `OPEN` for over 15 minutes without successful half-open recovery probes.
- **Impact**: All direct traffic to that upstream model is rejected or routed to fallback.
- **Runbook**: [`docs/operations-runbook.md#20-upstream-provider-outage--circuit-tripping`](operations-runbook.md#20-upstream-provider-outage--circuit-tripping). Check `/internal/provider-health`.

---

## 4. Disaster Recovery & Infrastructure Alerts

### `TollgateBackupStale` (P1 — Urgent)
- **Expression**: `time() - max(tollgate_backup_last_success_timestamp_seconds) > 7200`
- **Duration**: `15m`
- **Description**: No verified PostgreSQL backup has completed successfully in over 2 hours.
- **Impact**: Recovery Point Objective (RPO) target of 1 hour is at risk of violation.
- **Runbook**: [`docs/operations-runbook.md#21-backup-failure--stale-recovery-point`](operations-runbook.md#21-backup-failure--stale-recovery-point) or execute `bash scripts/backup_postgres.sh`.

### `TollgateHostDiskSpaceLow` (P1 — Urgent)
- **Expression**: `node_filesystem_free_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.15`
- **Duration**: `5m`
- **Description**: Host root filesystem free space is below 15%.
- **Impact**: Threatens PostgreSQL WAL archiving, Docker container logs, and backup dump writes.
- **Runbook**: [`docs/operations-runbook.md#23-disk-exhaustion--non-destructive-space-reclaim`](operations-runbook.md#23-disk-exhaustion--non-destructive-space-reclaim).

---

## Summary Matrix

| Alert Name | Severity | Condition | Primary Mitigation |
|---|---|---|---|
| `TollgateAPIUnavailable` | P0 | 0 active instances | Rebuild/restart container stack |
| `TollgatePostgresUnavailable` | P0 | DB ping fails | `scripts/recover_postgres.sh` |
| `TollgateRedisUnavailable` | P0 | Redis ping fails | `scripts/recover_redis.sh` |
| `TollgateWorkerBacklogIncreasing` | P1 | Pending > 5,000 | `scripts/recover_worker.sh` |
| `TollgateBackupStale` | P1 | Backup age > 2h | `scripts/backup_postgres.sh` |
| `TollgateCircuitPermanentlyOpen` | P1 | Circuit OPEN > 15m | Check upstream provider status |
| `TollgateHostDiskSpaceLow` | P1 | Free space < 15% | Prune Docker & old backups |
