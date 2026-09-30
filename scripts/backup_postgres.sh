#!/usr/bin/env bash
# ==============================================================================
# Tollgate PostgreSQL Automated Backup Script
# Creates a compressed, timestamped database dump without exposing credentials.
# ==============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
TIMESTAMP="$(date -u +"%Y%m%d_%H%M%SZ")"
BACKUP_FILE="${BACKUP_DIR}/tollgate_db_${TIMESTAMP}.sql.gz"

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-tollgate}"
DB_NAME="${POSTGRES_DB:-tollgate_db}"

mkdir -p "${BACKUP_DIR}"

echo "[INFO] Initiating PostgreSQL backup for database: '${DB_NAME}'"
echo "[INFO] Destination: '${BACKUP_FILE}'"

# Execute pg_dump using Docker container if running, or local pg_dump binary
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-postgres"; then
    echo "[INFO] Dumping database via running 'tollgate-postgres' Docker container..."
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-tollgate_secret_pass}" tollgate-postgres \
        pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists --no-owner --no-privileges \
        | gzip -9 > "${BACKUP_FILE}"
elif command -v pg_dump >/dev/null 2>&1; then
    echo "[INFO] Dumping database via host pg_dump binary..."
    PGPASSWORD="${POSTGRES_PASSWORD:-tollgate_secret_pass}" pg_dump \
        -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
        --clean --if-exists --no-owner --no-privileges \
        | gzip -9 > "${BACKUP_FILE}"
else
    echo "[ERROR] Neither running 'tollgate-postgres' container nor local 'pg_dump' utility was found." >&2
    exit 1
fi

# Verify backup file existence and non-zero size
if [[ ! -s "${BACKUP_FILE}" ]]; then
    echo "[ERROR] Backup failed: generated file '${BACKUP_FILE}' is missing or empty." >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

FILE_SIZE="$(du -h "${BACKUP_FILE}" | awk '{print $1}')"
echo "[SUCCESS] Backup created successfully: ${BACKUP_FILE} (Size: ${FILE_SIZE})"
