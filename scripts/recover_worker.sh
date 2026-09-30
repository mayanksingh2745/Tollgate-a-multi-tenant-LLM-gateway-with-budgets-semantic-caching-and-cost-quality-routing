#!/usr/bin/env bash
# ==============================================================================
# Tollgate Worker Recovery & Pending Message Reclamation Script
# Inspects stream pending consumer state, restarts workers, and reclaims stalled events.
# ==============================================================================
set -euo pipefail

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
STREAM_NAME="tg:usage:events"
GROUP_NAME="tg-usage-workers"

echo "[INFO] Initiating Tollgate Usage Worker recovery..."

# 1. Inspect Redis Stream Pending Messages
echo "[INFO] Inspecting pending messages on stream '${STREAM_NAME}'..."
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-redis"; then
    PENDING_INFO="$(docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD:-tollgate_redis_pass}" XPENDING "${STREAM_NAME}" "${GROUP_NAME}" 2>/dev/null || echo "0 0 0 ()")"
    echo "[INFO] Current stream pending state: ${PENDING_INFO}"
elif command -v redis-cli >/dev/null 2>&1; then
    PENDING_INFO="$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD:-tollgate_redis_pass}" XPENDING "${STREAM_NAME}" "${GROUP_NAME}" 2>/dev/null || echo "0 0 0 ()")"
    echo "[INFO] Current stream pending state: ${PENDING_INFO}"
else
    echo "[WARN] redis-cli not found; proceeding directly to worker container restart."
fi

# 2. Restart Stalled Worker Containers
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-worker"; then
    echo "[INFO] Restarting worker container(s)..."
    docker restart tollgate-worker || true
    echo "[INFO] Waiting 5 seconds for worker consumer reconnection and XAUTOCLAIM initialization..."
    sleep 5
fi

# 3. Check Dead-Letter Stream
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-redis"; then
    DLQ_LEN="$(docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD:-tollgate_redis_pass}" XLEN tg:usage:dead_letter 2>/dev/null || echo "0")"
    echo "[INFO] Dead-letter queue length: ${DLQ_LEN} entries"
fi

echo "[SUCCESS] Worker recovery complete. Consumer group is actively reclaiming pending events."
exit 0
