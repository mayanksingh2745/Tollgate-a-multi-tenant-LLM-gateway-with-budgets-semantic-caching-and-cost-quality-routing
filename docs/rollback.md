# Production Rollback Strategy & Procedures (Phase 15A)

## 1. Rollback Philosophy & Architecture

In production, rollbacks must be safe, fast, and deterministic. Tollgate decouples application code rollbacks from database schema rollbacks to prevent accidental data corruption or loss.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Tollgate Rollback Tiers                         │
├──────────────────────────┬──────────────────────────┬──────────────────┤
│ 1. Application Rollback  │ 2. Configuration Rollback│ 3. DB Migration  │
├──────────────────────────┼──────────────────────────┼──────────────────┤
│ Fast & Safe              │ Fast & Safe              │ High-Risk Manual │
│ Restarts services with   │ Reverts .env variables   │ Requires explicit│
│ immutable Docker images  │ and restarts containers  │ data analysis &  │
│ (e.g. tag <git-sha>)     │                          │ backup snapshot  │
└──────────────────────────┴──────────────────────────┴──────────────────┘
```

---

## 2. Distinction Between Rollback Types

### A. Application Rollback (Code / Containers)
* **When to use**: A newly deployed application release exhibits elevated error rates, memory leaks, or functional bugs.
* **Mechanism**: Swapping container image tags to a previously verified Git SHA (`tollgate-api:<prev-sha>`).
* **Database Impact**: Zero database mutations occur. Because Tollgate migrations follow **expand-and-contract** design patterns, previous application versions remain compatible with newer database columns.

### B. Configuration Rollback
* **When to use**: An incorrect environment variable was introduced (e.g., misconfigured rate limits, bad CORS origin, or malformed timeout value).
* **Mechanism**: Revert the `.env` configuration file to its prior state and execute:
  ```bash
  docker compose -f docker-compose.prod.yml up -d
  ```

### C. Database Migration Rollback (CAUTION)
* **When to use**: ONLY when a newly applied schema migration itself was flawed and cannot be patched forward.
* **Warning**: Never automatically downgrade database migrations during an application rollback. Rolling back migrations that dropped or altered columns will cause irreversible data loss unless restored from a backup.
* **Procedure**:
  1. Capture a fresh snapshot backup immediately via `./scripts/backup_postgres.sh`.
  2. Inspect the down revision:
     ```bash
     python -m alembic history
     ```
  3. Manually downgrade one revision:
     ```bash
     python -m alembic downgrade -1
     ```

---

## 3. Step-by-Step Application Rollback

To roll back the running deployment to a previously verified release:

```bash
# 1. Execute rollback script with target Git commit SHA
./scripts/rollback.sh <known_good_git_sha>

# Example:
./scripts/rollback.sh c555c0c
```

### What the script executes:
1. **Validates Image Availability**: Verifies whether `tollgate-api:<sha>` and `tollgate-worker:<sha>` exist locally. If missing, builds them deterministically from the specified Git tag.
2. **Recreates Containers**: Invokes Docker Compose with the target image tags.
3. **Polls Readiness Probe**: Polls `GET /health/ready` until all components confirm healthy status.
4. **Verifies Release Version**: Checks `GET /health/version` to confirm the active Git SHA matches `<known_good_git_sha>`.
5. **Returns Exit Code**: Exits 0 on verified success, or non-zero on failure.
