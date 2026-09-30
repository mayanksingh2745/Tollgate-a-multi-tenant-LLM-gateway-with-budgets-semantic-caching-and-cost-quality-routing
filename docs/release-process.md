# Release Process

Step-by-step process for releasing a new version of Tollgate.

---

## 1. Branching

All feature work happens on feature branches:

```bash
git checkout main
git pull origin main
git checkout -b feat/<feature-name>
```

Bugfixes for production use `fix/` prefix:

```bash
git checkout -b fix/<issue-description>
```

---

## 2. Development & Testing

### Local Testing

```bash
# Run full test suite
pytest tests/ --ignore=tests/test_benchmarks.py -q

# Run security tests
pytest tests/security/ -v

# Run specific phase tests
pytest tests/test_health.py tests/test_migrations.py -v
```

### Docker Testing

```bash
# Validate compose files
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.staging.yml config --quiet

# Build and test locally
docker compose up -d --build
curl -s http://localhost:8000/health/ready
docker compose down
```

---

## 3. Pull Request

```bash
git push origin feat/<feature-name>
gh pr create --base main --title "feat: <description>"
```

### PR CI Pipeline (`ci.yml`)

The PR validation pipeline runs:

| Job | Description |
|-----|-------------|
| Security Audit | pip-audit + secret scan |
| Lint & Type Check | black, ruff, mypy |
| Unit & Integration Tests | Full pytest suite (excluding benchmarks) |
| Security Tests | Phase 14 security test suite |
| Frontend Build | Dashboard npm ci + build |
| Docker Build | Gateway + Worker image builds |
| Config Validation | Compose file + nginx syntax validation |

All jobs must pass before merge.

---

## 4. Versioning

Tollgate uses semantic versioning:

```
MAJOR.MINOR.PATCH
```

- **MAJOR**: Breaking API changes
- **MINOR**: New features, backwards-compatible
- **PATCH**: Bug fixes, security patches

Version is set via:
- `TOLLGATE_VERSION` environment variable
- Git tags: `v1.0.0`, `v1.1.0`, etc.

---

## 5. Image Build

Container images are tagged with immutable identifiers:

| Tag | Source | Example |
|-----|--------|---------|
| Git SHA (short) | Every build | `tollgate-api:a1b2c3d` |
| Branch name | Branch builds | `tollgate-api:main` |
| Semantic version | Tagged releases | `tollgate-api:1.0.0` |

**Never rely solely on `latest` for production.**

### Registry

Images are pushed to GitHub Container Registry (GHCR):

```
ghcr.io/<owner>/tollgate-api:<tag>
ghcr.io/<owner>/tollgate-worker:<tag>
ghcr.io/<owner>/tollgate-dashboard:<tag>
```

Authentication uses `GITHUB_TOKEN` (automatic in CI).

### Retention

- SHA-tagged images: retained for 90 days
- Branch-tagged images: retained for 30 days
- Version-tagged images: retained indefinitely

---

## 6. Staging Deployment

Automatically triggered on push to `main` via `release.yml`:

```
main push → CI → Build Images → Deploy Staging → Smoke Tests
```

Staging uses:
- `docker-compose.staging.yml`
- Separate database and Redis
- Staging-specific credentials (GitHub Environment: `staging`)
- Debug logging enabled
- API docs enabled

### Staging Verification

```bash
GATEWAY_URL=http://localhost:8080 bash scripts/smoke_test.sh
```

---

## 7. Production Approval

Production deployment requires manual approval via GitHub Environment: `production`.

Required reviewers must approve before the deployment job runs.

Production secrets (database password, Redis password, metrics token) are scoped to the `production` environment and are never available to PR builds or staging.

---

## 8. Production Deployment

### Automated (via GitHub Actions)

After staging passes and approval is granted:

```
Staging → Approval → Migrate → Deploy → Readiness → Smoke Tests
```

### Manual Deployment

```bash
# 1. Create backup
bash scripts/backup_postgres.sh

# 2. Record current version
curl -s http://localhost:8000/health/version

# 3. Deploy
TOLLGATE_GIT_COMMIT=$(git rev-parse --short HEAD) bash scripts/deploy.sh

# 4. Verify
bash scripts/smoke_test.sh
bash scripts/validate_deployment.sh
bash scripts/security_validate.sh
```

---

## 9. Post-Deployment Verification

After every production deployment:

1. **Health**: `GET /health/ready` → 200
2. **Version**: `GET /health/version` → verify git SHA matches deployed commit
3. **Smoke Tests**: `bash scripts/smoke_test.sh`
4. **Deployment Validation**: `bash scripts/validate_deployment.sh`
5. **Security Validation**: `bash scripts/security_validate.sh`
6. **Metrics**: Check Grafana dashboards for anomalies
7. **Logs**: `docker logs tollgate-gateway --tail=50`

---

## 10. Rollback

If any post-deployment check fails:

```bash
# Rollback to previous known-good commit
bash scripts/rollback.sh <previous_git_sha>

# Verify recovery
bash scripts/smoke_test.sh

# If database migration was applied, assess compatibility
# Previous application version must be compatible with current schema
# NEVER run alembic downgrade in production without explicit approval
```

### Migration Rollback Safety

Tollgate migrations are designed to be forward-compatible:
- Adding columns: safe (old app ignores new columns)
- Removing columns: unsafe (old app may reference them)
- Adding tables: safe
- Removing tables: unsafe

If a migration is not backward-compatible, the rollback documentation must specify this limitation.

---

## 11. Emergency Hotfix

```bash
# 1. Create fix branch from main
git checkout main
git pull origin main
git checkout -b fix/<issue>

# 2. Implement fix
# 3. Test locally
pytest tests/ -q

# 4. Push and create PR
git push origin fix/<issue>
gh pr create --base main --title "fix: <description>"

# 5. After CI passes and approval, merge
# 6. Deploy following standard process
```
