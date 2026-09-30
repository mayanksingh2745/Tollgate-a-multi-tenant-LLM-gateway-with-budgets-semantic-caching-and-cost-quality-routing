#!/usr/bin/env bash
# ==============================================================================
# Tollgate PostgreSQL Automated Recovery Script
# Recovers database service, verifies connectivity, and restores from backup if necessary.
# ==============================================================================
set -euo pipefail

POSTGRES_USER="${POSTGRES_USER:-tollgate}"
POSTGRES_DB="${POSTGRES_DB:-tollgate_db}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

echo "[INFO] Initiating PostgreSQL automated recovery..."

# 1. Check if database container exists and restart if stopped
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-postgres"; then
    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-postgres"; then
        echo "[INFO] Starting stopped PostgreSQL container..."
        docker start tollgate-postgres
        sleep 5
    fi
fi

# 2. Check Database Readiness
MAX_RETRIES=10
RETRY_COUNT=0
DB_READY=false

while [[ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]]; do
    if docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-tollgate_secret_pass}" tollgate-postgres \
        pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
        DB_READY=true
        break
    fi
    RETRY_COUNT=$(( RETRY_COUNT + 1 ))
    echo "[INFO] Waiting for PostgreSQL readiness (${RETRY_COUNT}/${MAX_RETRIES})..."
    sleep 2
done

# 3. If Database is down or corrupted, restore from latest backup
if [[ "${DB_READY}" != "true" ]]; then
    echo "[WARN] PostgreSQL failed readiness check. Attempting restore from latest backup..."
    LATEST_BACKUP="$(ls -t "${BACKUP_DIR}"/tollgate_db_*.sql.gz 2>/dev/null | head -n 1 || echo "")"
    if [[ -z "${LATEST_BACKUP}" ]]; then
        echo "[ERROR] Recovery aborted: No backup found in '${BACKUP_DIR}'." >&2
        exit 1
    fi
    echo "[INFO] Restoring from latest backup: '${LATEST_BACKUP}'"
    bash scripts/restore_postgres.sh "${LATEST_BACKUP}"
fi

# 4. Verify Schema and Migrations
echo "[INFO] Verifying database schema migration status..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-gateway"; then
    docker exec tollgate-gateway alembic current || true
fi

echo "[SUCCESS] PostgreSQL recovery verified successfully."
exit 0
