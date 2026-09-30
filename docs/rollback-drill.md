# Rollback Drill Runbook

This document is a step-by-step runbook for executing a rollback drill against Tollgate.

A rollback drill validates that the `scripts/rollback.sh` script can revert a bad deployment to the previous known-good state within the target recovery time.

---

## Prerequisites

- Docker and Docker Compose installed
- Access to the production host (or staging equivalent)
- The previous deployment's image tag (format: `tollgate-api:<git-commit>`)
- The `scripts/rollback.sh` script is executable

---

## Drill Procedure

### Step 1: Record Current State

```bash
# Record current running image tags
docker inspect --format='{{.Config.Image}}' tollgate-gateway
docker inspect --format='{{.Config.Image}}' tollgate-worker
curl -s http://localhost:8000/health/version | python3 -m json.tool
```

Document:
- Current image tag
- Current version
- Current git commit
- Timestamp

### Step 2: Simulate Bad Deployment

Deploy a known change (e.g., set an intentionally wrong environment variable or use a test image tag):

```bash
# Option A: Deploy with a test commit
TOLLGATE_GIT_COMMIT=bad-deploy-test bash scripts/deploy.sh

# Option B: Manually break a non-critical config
docker exec tollgate-gateway env | grep ENVIRONMENT
```

### Step 3: Verify Bad State

```bash
# Confirm the "bad" deployment is running
curl -s http://localhost:8000/health/version
# Confirm the version/commit changed
```

### Step 4: Execute Rollback

```bash
# Roll back to the previous good tag
PREVIOUS_TAG="<recorded-git-commit>"
bash scripts/rollback.sh "${PREVIOUS_TAG}"
```

**Target: Rollback should complete in under 60 seconds.**

### Step 5: Validate Recovery

```bash
# 1. Health check
curl -s http://localhost:8000/health/ready

# 2. Version should show previous tag
curl -s http://localhost:8000/health/version

# 3. Run smoke tests
bash scripts/smoke_test.sh
```

### Step 6: Record Results

| Metric | Value |
|--------|-------|
| Drill Date | |
| Rollback Duration | |
| Health Check Passed | Yes / No |
| Smoke Tests Passed | Yes / No |
| Data Loss | None / Describe |
| Operator | |
| Notes | |

---

## Success Criteria

- [ ] Rollback completed in < 60 seconds
- [ ] `/health/ready` returns 200 after rollback
- [ ] `/health/version` shows the previous version
- [ ] Smoke tests pass after rollback
- [ ] No data loss during rollback
- [ ] Worker reconnects to Redis and resumes processing

---

## Failure Scenarios to Test

| Scenario | Expected Behavior |
|----------|-------------------|
| Previous image not available locally | `rollback.sh` fails with clear error |
| Database migration incompatible | Application starts but readiness fails |
| Redis data format mismatch | Cache misses; no crash |
| Worker fails to reconnect | Worker container restarts via `restart: always` |

---

## Post-Drill Cleanup

```bash
# If drill was performed on staging, tear down:
docker compose -f docker-compose.staging.yml down -v

# If drill was performed on production, verify everything is healthy:
bash scripts/smoke_test.sh
bash scripts/validate_deployment.sh
```
