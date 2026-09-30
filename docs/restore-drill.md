# Restore Drill Runbook

This document is a step-by-step runbook for executing a database restore drill against Tollgate.

A restore drill validates that `scripts/backup_postgres.sh` and `scripts/restore_postgres.sh` can reliably backup and restore the PostgreSQL database with zero data loss.

---

## Prerequisites

- Docker and Docker Compose installed
- Access to the production host (or staging equivalent)
- The `scripts/backup_postgres.sh` and `scripts/restore_postgres.sh` scripts are executable
- Sufficient disk space for backup files in `./backups/`

---

## Drill Procedure

### Step 1: Record Current Database State

```bash
# Check current row counts for key tables
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "
  SELECT 'tenants' as tbl, count(*) FROM tenants
  UNION ALL SELECT 'projects', count(*) FROM projects
  UNION ALL SELECT 'api_keys', count(*) FROM api_keys
  UNION ALL SELECT 'usage_records', count(*) FROM usage_records;
"
```

Record:
- Row counts for each table
- Current timestamp
- Current database size

### Step 2: Create Backup

```bash
bash scripts/backup_postgres.sh
```

Verify backup was created:

```bash
ls -lah backups/
# Should show a file like: tollgate_backup_YYYYMMDD_HHMMSS.sql.gz
```

Record:
- Backup filename
- Backup file size
- Backup duration

### Step 3: Verify Backup Integrity

```bash
# Decompress and check SQL structure (do NOT restore yet)
BACKUP_FILE=$(ls -t backups/tollgate_backup_*.sql.gz | head -1)
gunzip -c "${BACKUP_FILE}" | head -50
gunzip -c "${BACKUP_FILE}" | grep "CREATE TABLE" | wc -l
```

### Step 4: Insert Test Data

```bash
# Insert a known marker row to verify restore removes it
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "
  CREATE TABLE IF NOT EXISTS _restore_drill_marker (
    id SERIAL PRIMARY KEY,
    marker TEXT DEFAULT 'THIS_SHOULD_NOT_EXIST_AFTER_RESTORE',
    created_at TIMESTAMP DEFAULT NOW()
  );
  INSERT INTO _restore_drill_marker (marker) VALUES ('drill_marker_$(date +%s)');
"
```

### Step 5: Execute Restore

```bash
BACKUP_FILE=$(ls -t backups/tollgate_backup_*.sql.gz | head -1)
bash scripts/restore_postgres.sh "${BACKUP_FILE}"
```

**Target: Restore should complete in under 5 minutes for typical database sizes.**

### Step 6: Validate Restore

```bash
# 1. Marker table should NOT exist (restore replaces entire DB)
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "
  SELECT count(*) FROM _restore_drill_marker;
" 2>&1 | grep -q "does not exist" && echo "PASS: Marker removed" || echo "FAIL: Marker still exists"

# 2. Row counts should match pre-backup state
docker exec tollgate-postgres psql -U tollgate -d tollgate_db -c "
  SELECT 'tenants' as tbl, count(*) FROM tenants
  UNION ALL SELECT 'projects', count(*) FROM projects
  UNION ALL SELECT 'api_keys', count(*) FROM api_keys
  UNION ALL SELECT 'usage_records', count(*) FROM usage_records;
"

# 3. Application health
curl -s http://localhost:8000/health/ready

# 4. Run smoke tests
bash scripts/smoke_test.sh
```

### Step 7: Record Results

| Metric | Value |
|--------|-------|
| Drill Date | |
| Backup Duration | |
| Backup File Size | |
| Restore Duration | |
| Row Count Match | Yes / No |
| Marker Removed | Yes / No |
| Health Check Passed | Yes / No |
| Smoke Tests Passed | Yes / No |
| Operator | |
| Notes | |

---

## Success Criteria

- [ ] Backup completed without errors
- [ ] Backup file is non-empty and contains valid SQL
- [ ] Restore completed without errors
- [ ] Test marker data does NOT exist after restore
- [ ] Row counts match pre-backup state
- [ ] `/health/ready` returns 200 after restore
- [ ] Smoke tests pass after restore
- [ ] Alembic migrations are at correct head after restore

---

## Failure Scenarios to Test

| Scenario | Expected Behavior |
|----------|-------------------|
| Corrupted backup file | `restore_postgres.sh` fails with clear error |
| Insufficient disk space | `backup_postgres.sh` fails before completing |
| Database locked during backup | Backup uses pg_dump which handles concurrent access |
| Network interruption during restore | Restore fails; original data may be lost (hence backup-before-restore) |
| Wrong database credentials | Scripts fail with authentication error |

---

## Post-Drill Cleanup

```bash
# If drill was performed on staging:
docker compose -f docker-compose.staging.yml down -v

# If drill was performed on production:
# Clean up old backup files (keep last 7 days)
find backups/ -name "tollgate_backup_*.sql.gz" -mtime +7 -delete

# Verify everything is healthy
bash scripts/smoke_test.sh
```

---

## Recommended Schedule

| Environment | Frequency |
|-------------|-----------|
| Staging | Weekly |
| Production | Monthly |
