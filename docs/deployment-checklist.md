# Production Deployment Checklist

Complete checklist for deploying Tollgate to production. Every item must pass before traffic is routed.

---

## Pre-Deployment

### Code Quality
- [ ] All CI pipeline jobs pass (lint, type check, tests, Docker build)
- [ ] No critical or high-severity vulnerabilities in `pip-audit`
- [ ] Secret scanner finds no leaked credentials
- [ ] Migration chain is linear and complete (`test_migrations.py` passes)

### Configuration
- [ ] `.env` file contains all required production variables
- [ ] `ENVIRONMENT=production` is set
- [ ] `POSTGRES_PASSWORD` is a strong, unique password (not the default)
- [ ] `REDIS_PASSWORD` is set
- [ ] `TOLLGATE_METRICS_TOKEN` is set
- [ ] `TOLLGATE_CORS_ALLOWED_ORIGINS` is NOT `*`
- [ ] `TOLLGATE_DOCS_ENABLED=false` (API docs disabled in production)
- [ ] `DEBUG=false` or unset
- [ ] `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` are set if using those providers

### Infrastructure
- [ ] Docker and Docker Compose are installed and up to date
- [ ] PostgreSQL data volume exists and has adequate disk space
- [ ] Redis volume exists
- [ ] Backup directory exists: `mkdir -p backups/`
- [ ] Network configuration reviewed (no public exposure of Postgres/Redis)

---

## Deployment

### Execution
```bash
# 1. Create a backup of the current database
bash scripts/backup_postgres.sh

# 2. Record current version for rollback reference
curl -s http://localhost:8000/health/version | python3 -m json.tool

# 3. Deploy
bash scripts/deploy.sh
```

### Verification Steps (Automated)
```bash
# Run all validation scripts
bash scripts/smoke_test.sh
bash scripts/validate_deployment.sh
bash scripts/security_validate.sh
```

---

## Post-Deployment

### Immediate (within 5 minutes)
- [ ] `/health/ready` returns 200
- [ ] `/health/version` shows correct version and commit
- [ ] Smoke tests pass
- [ ] Deployment validation passes
- [ ] Security validation passes
- [ ] Check application logs for errors: `docker logs tollgate-gateway --tail=50`
- [ ] Check worker logs: `docker logs tollgate-worker --tail=50`

### Short-term (within 1 hour)
- [ ] Monitor Grafana dashboards for anomalies
- [ ] Verify usage pipeline is processing events (check worker logs)
- [ ] Verify Prometheus is scraping metrics
- [ ] Verify no elevated error rates in API responses

### Ongoing
- [ ] Set up alerting for:
  - Gateway health check failures
  - Worker restarts
  - Database connection pool exhaustion
  - Redis memory usage > 80%
  - Error rate > 5%
  - p99 latency > 10s

---

## Rollback Procedure

If any post-deployment check fails:

```bash
# 1. Execute rollback to previous version
bash scripts/rollback.sh <previous-git-commit>

# 2. Verify recovery
bash scripts/smoke_test.sh

# 3. If database migration caused issues, restore from backup
bash scripts/restore_postgres.sh backups/<latest-backup>.sql.gz
```

---

## Emergency Contacts

| Role | Contact |
|------|---------|
| On-call Engineer | |
| Database Admin | |
| Security Lead | |

---

## Version History

| Date | Version | Commit | Deployer | Notes |
|------|---------|--------|----------|-------|
| | | | | |
