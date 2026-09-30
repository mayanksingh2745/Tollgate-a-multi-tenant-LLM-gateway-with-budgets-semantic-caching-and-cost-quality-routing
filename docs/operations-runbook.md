# Operations Runbook

Actionable procedures for common operational incidents in Tollgate.

All commands assume access to the production Docker Compose host running `docker-compose.prod.yml`.

---

## 1. API Gateway Outage

**Symptoms**: `/health/ready` returns 503 or connection refused; Grafana alerts on error rate.

**Diagnosis**:
```bash
docker inspect --format='{{.State.Status}}' tollgate-gateway
docker logs tollgate-gateway --tail=50
curl -s http://localhost:8000/health/live
curl -s http://localhost:8000/health/ready
```

**Resolution**:
```bash
# 1. Restart gateway
docker restart tollgate-gateway

# 2. Wait for readiness (max 60s)
for i in $(seq 1 30); do
  curl -s -f http://localhost:8000/health/ready && break
  sleep 2
done

# 3. Verify version
curl -s http://localhost:8000/health/version

# 4. If restart fails, check dependencies
docker logs tollgate-postgres --tail=20
docker logs tollgate-redis --tail=20

# 5. If persistent, rollback
bash scripts/rollback.sh <previous_git_sha>
```

---

## 2. Worker Outage

**Symptoms**: Usage events accumulate in Redis stream; no new usage records in PostgreSQL.

**Diagnosis**:
```bash
docker inspect --format='{{.State.Status}}' tollgate-worker
docker logs tollgate-worker --tail=50
# Check pending messages
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XLEN tg:usage:events
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XPENDING tg:usage:events tg-usage-workers - + 10
```

**Resolution**:
```bash
# 1. Restart worker
docker restart tollgate-worker

# 2. Verify processing resumes (check pending count decreasing)
sleep 10
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XPENDING tg:usage:events tg-usage-workers - + 5

# 3. Worker uses XAUTOCLAIM to reclaim abandoned messages automatically
```

---

## 3. Redis Outage

**Symptoms**: Rate limiting fails; cache misses increase; readiness probe returns 503.

**Diagnosis**:
```bash
docker inspect --format='{{.State.Status}}' tollgate-redis
docker logs tollgate-redis --tail=20
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" ping
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" info memory
```

**Resolution**:
```bash
# 1. Restart Redis
docker restart tollgate-redis

# 2. Wait for health
for i in $(seq 1 15); do
  docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" ping && break
  sleep 2
done

# 3. Verify gateway recovers
curl -s http://localhost:8000/health/ready

# 4. Cache will rebuild naturally; rate limit counters reset
# 5. Worker will reconnect and resume stream processing
```

**Important**: Redis restart clears in-memory rate limit state and cache. This is expected; the system is designed to recover gracefully.

---

## 4. PostgreSQL Outage

**Symptoms**: Readiness probe fails; API returns 500 on authenticated requests; worker cannot persist usage.

**Diagnosis**:
```bash
docker inspect --format='{{.State.Status}}' tollgate-postgres
docker logs tollgate-postgres --tail=30
docker exec tollgate-postgres pg_isready -U tollgate -d tollgate_db
```

**Resolution**:
```bash
# 1. Restart PostgreSQL
docker restart tollgate-postgres

# 2. Wait for readiness
for i in $(seq 1 15); do
  docker exec tollgate-postgres pg_isready -U tollgate && break
  sleep 2
done

# 3. Verify API recovery
curl -s http://localhost:8000/health/ready

# 4. If data corruption suspected, restore from backup
bash scripts/restore_postgres.sh backups/<latest_backup>.sql.gz
```

---

## 5. Provider Outage (Upstream LLM)

**Symptoms**: Chat completions fail with 502/503; circuit breaker opens; fallback triggered.

**Diagnosis**:
```bash
# Check circuit breaker status
curl -s http://localhost:8000/internal/provider-health | python3 -m json.tool

# Check Prometheus metrics
# tollgate_provider_failures_total
# tollgate_circuit_breaker_state
```

**Resolution**:
```bash
# 1. Circuit breaker will automatically probe and recover when provider returns
# 2. Verify fallback providers are configured
# 3. If all providers are down, inform users
# 4. Monitor circuit breaker state via /internal/provider-health
```

---

## 6. Usage Stream Backlog

**Symptoms**: `XLEN tg:usage:events` growing; usage records delayed in PostgreSQL.

**Diagnosis**:
```bash
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XLEN tg:usage:events
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XPENDING tg:usage:events tg-usage-workers - + 20
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XLEN tg:usage:dead-letter
docker logs tollgate-worker --tail=50
```

**Resolution**:
```bash
# 1. Check worker health
docker inspect --format='{{.State.Status}}' tollgate-worker

# 2. Restart worker if stuck
docker restart tollgate-worker

# 3. If dead letter stream has entries, investigate
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XRANGE tg:usage:dead-letter - + COUNT 5

# 4. Worker will XAUTOCLAIM orphaned messages on restart
```

---

## 7. Failed Database Migration

**Symptoms**: `alembic upgrade head` fails; API cannot start after deployment.

**Resolution**:
```bash
# 1. Check current migration head
python -m alembic current

# 2. View migration history
python -m alembic history

# 3. If migration failed midway, check database state
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "SELECT * FROM alembic_version;"

# 4. If safe, retry migration
python -m alembic upgrade head

# 5. If migration is incompatible, rollback application
bash scripts/rollback.sh <previous_git_sha>

# 6. NEVER run alembic downgrade in production without explicit approval
```

---

## 8. Failed Deployment

**Symptoms**: `deploy.sh` fails or readiness probe times out after deployment.

**Resolution**:
```bash
# 1. Check what failed
docker compose -f docker-compose.prod.yml ps
docker logs tollgate-gateway --tail=50

# 2. Rollback to previous version
bash scripts/rollback.sh <previous_git_sha>

# 3. Verify recovery
bash scripts/smoke_test.sh

# 4. Investigate root cause before re-deploying
```

---

## 9. Rollback Procedure

```bash
# 1. Identify last known-good commit
git log --oneline -10

# 2. Execute rollback
bash scripts/rollback.sh <known_good_sha>

# 3. Verify
curl -s http://localhost:8000/health/version
bash scripts/smoke_test.sh
```

---

## 10. Database Restore

```bash
# 1. Create a backup of current state (even if corrupted)
bash scripts/backup_postgres.sh

# 2. Restore from known-good backup
bash scripts/restore_postgres.sh backups/<backup_file>.sql.gz

# 3. Verify schema
python -m alembic current

# 4. Verify application
curl -s http://localhost:8000/health/ready
bash scripts/smoke_test.sh
```

---

## 11. Secret Rotation

### API Keys (Tollgate tenant API keys)
```bash
# Tenant API keys are hashed in PostgreSQL
# Rotation: tenant admin creates new key, deactivates old key via dashboard
```

### PostgreSQL Password
```bash
# 1. Update password in PostgreSQL
docker exec tollgate-postgres psql -U tollgate -c "ALTER USER tollgate PASSWORD 'new_password';"

# 2. Update .env and restart services
# Update POSTGRES_PASSWORD and DATABASE_URL in .env
docker compose -f docker-compose.prod.yml up -d gateway worker
```

### Redis Password
```bash
# 1. Update .env with new REDIS_PASSWORD
# 2. Recreate Redis container with new password
docker compose -f docker-compose.prod.yml up -d redis
# 3. Restart dependent services
docker compose -f docker-compose.prod.yml restart gateway worker
```

### Metrics Token
```bash
# 1. Update TOLLGATE_METRICS_TOKEN in .env
# 2. Restart gateway
docker restart tollgate-gateway
# 3. Update Prometheus scrape config with new token
```

---

## 12. Certificate Renewal

```bash
# NGINX reverse proxy handles TLS termination
# If using Let's Encrypt with certbot:
# certbot renew
# docker restart tollgate-proxy

# If using manually provisioned certificates:
# 1. Replace certificate files in infra/nginx/certs/
# 2. docker restart tollgate-proxy
```

---

## 13. Disk Exhaustion

**Diagnosis**:
```bash
df -h
docker system df
du -sh /var/lib/docker/volumes/*
ls -lh backups/
```

**Resolution**:
```bash
# 1. Clean old Docker images
docker image prune -a --filter "until=168h"

# 2. Clean old backups (keep last 7 days)
find backups/ -name "tollgate_backup_*.sql.gz" -mtime +7 -delete

# 3. Clean Docker build cache
docker builder prune -f

# 4. Verify Prometheus retention is bounded
# Check prometheus --storage.tsdb.retention.time setting

# 5. Check Docker log sizes
docker inspect --format='{{.LogPath}}' tollgate-gateway | xargs ls -lh
```

---

## 14. High Memory Usage

**Diagnosis**:
```bash
docker stats --no-stream
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" info memory
```

**Resolution**:
```bash
# 1. Redis: Check maxmemory policy is set
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" config get maxmemory
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" config get maxmemory-policy

# 2. Gateway: Restart if memory leak suspected
docker restart tollgate-gateway

# 3. PostgreSQL: Check connection count
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "SELECT count(*) FROM pg_stat_activity;"
```

---

## 15. High CPU Usage

**Diagnosis**:
```bash
docker stats --no-stream
top -bn1 | head -20
```

**Resolution**:
```bash
# 1. Identify which container
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# 2. If gateway: check for request spike
# Review Prometheus: tollgate_http_requests_total rate

# 3. If worker: check stream processing rate
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD}" XLEN tg:usage:events

# 4. If PostgreSQL: check slow queries
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "SELECT pid, query, state, now() - query_start as duration FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC LIMIT 5;"
```
