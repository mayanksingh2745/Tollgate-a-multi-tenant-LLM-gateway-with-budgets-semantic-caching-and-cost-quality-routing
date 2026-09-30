#!/usr/bin/env bash
# ==============================================================================
# Tollgate Master Disaster Recovery Orchestration Script
# Handles cold-host reconstitution, database restore, Redis recovery, and rollbacks.
# ==============================================================================
set -euo pipefail

SCENARIO="${1:---all}"

echo "=================================================="
echo "       Tollgate Disaster Recovery Orchestrator    "
echo "=================================================="
echo "[INFO] Target scenario: '${SCENARIO}'"

case "${SCENARIO}" in
    --scenario=postgres|postgres)
        echo "[INFO] Executing Scenario B — PostgreSQL Loss Recovery..."
        bash scripts/recover_postgres.sh
        ;;
    --scenario=redis|redis)
        echo "[INFO] Executing Scenario C — Redis Loss Recovery..."
        bash scripts/recover_redis.sh
        ;;
    --scenario=worker|worker)
        echo "[INFO] Executing Worker Loss Recovery..."
        bash scripts/recover_worker.sh
        ;;
    --scenario=rollback|rollback)
        PREV_COMMIT="${2:-HEAD~1}"
        echo "[INFO] Executing Scenario D — Corrupted Deployment Rollback to '${PREV_COMMIT}'..."
        bash scripts/rollback.sh "${PREV_COMMIT}"
        ;;
    --scenario=host|host|--all)
        echo "[INFO] Executing Scenario A — Cold Host / Stack Reconstitution..."
        if docker compose version >/dev/null 2>&1; then
            echo "[INFO] Reconstituting full stack via Docker Compose..."
            docker compose -f docker-compose.prod.yml up -d --remove-orphans
        fi
        sleep 5
        bash scripts/recover_postgres.sh
        bash scripts/recover_redis.sh
        bash scripts/recover_worker.sh
        ;;
    *)
        echo "[ERROR] Unknown scenario '${SCENARIO}'. Available: host, postgres, redis, worker, rollback, --all" >&2
        exit 1
        ;;
esac

echo ""
echo "[INFO] Running post-recovery health check verification..."
bash scripts/health_check.sh

echo ""
echo "[SUCCESS] Disaster recovery sequence completed successfully."
exit 0
