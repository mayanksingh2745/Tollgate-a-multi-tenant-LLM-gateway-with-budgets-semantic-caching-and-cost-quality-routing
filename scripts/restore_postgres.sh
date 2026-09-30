#!/usr/bin/env bash
# ==============================================================================
# Tollgate PostgreSQL Automated Restore Script
# Restores a compressed database dump into PostgreSQL with safety confirmations.
# ==============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path_to_backup_file.sql.gz> [--force]" >&2
    exit 1
fi

BACKUP_FILE="$1"
FORCE="${2:-}"

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "[ERROR] Backup file '${BACKUP_FILE}' does not exist or is not readable." >&2
    exit 1
fi

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-tollgate}"
DB_NAME="${POSTGRES_DB:-tollgate_db}"

echo "======================================================================"
echo " [DANGER] DESTRUCTIVE ACTION: RESTORING TOLLGATE DATABASE"
echo " Target database: '${DB_NAME}' at ${DB_HOST}:${DB_PORT}"
echo " Source file:     '${BACKUP_FILE}'"
echo " WARNING: this will overwrite all existing tables and data in '${DB_NAME}'."
echo "======================================================================"

if [[ "${FORCE}" != "--force" ]]; then
    echo "To proceed, type exactly: RESTORE TOLLGATE"
    read -r -p "> " CONFIRMATION
    if [[ "${CONFIRMATION}" != "RESTORE TOLLGATE" ]]; then
        echo "[ABORTED] Confirmation string did not match. Aborting database restore." >&2
        exit 1
    fi
fi

echo "[INFO] Restoring database from '${BACKUP_FILE}'..."

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-postgres"; then
    echo "[INFO] Restoring via running 'tollgate-postgres' Docker container..."
    gunzip -c "${BACKUP_FILE}" | docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD:-tollgate_secret_pass}" tollgate-postgres \
        psql -U "${DB_USER}" -d "${DB_NAME}"
elif command -v psql >/dev/null 2>&1; then
    echo "[INFO] Restoring via host psql binary..."
    gunzip -c "${BACKUP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD:-tollgate_secret_pass}" psql \
        -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}"
else
    echo "[ERROR] Neither running 'tollgate-postgres' container nor local 'psql' utility was found." >&2
    exit 1
fi

echo "[SUCCESS] Database restoration complete for '${DB_NAME}'."
