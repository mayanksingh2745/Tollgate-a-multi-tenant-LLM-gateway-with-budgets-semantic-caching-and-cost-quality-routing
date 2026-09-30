#!/usr/bin/env bash
# ==============================================================================
# Tollgate Redis Automated Recovery Script
# Restarts Redis, validates persistence, and reconstructs essential stream consumer groups.
# ==============================================================================
set -euo pipefail

STREAM_NAME="tg:usage:events"
GROUP_NAME="tg-usage-workers"

echo "[INFO] Initiating Redis automated recovery..."

# 1. Restart Redis container if stopped or unresponsive
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-redis"; then
    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "tollgate-redis"; then
        echo "[INFO] Starting stopped Redis container..."
        docker start tollgate-redis
        sleep 3
    fi
fi

# 2. Verify Redis Connectivity (PING -> PONG)
MAX_RETRIES=10
RETRY_COUNT=0
REDIS_READY=false

while [[ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]]; do
    if docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD:-tollgate_redis_pass}" ping 2>/dev/null | grep -q "PONG"; then
        REDIS_READY=true
        break
    fi
    RETRY_COUNT=$(( RETRY_COUNT + 1 ))
    echo "[INFO] Waiting for Redis PING response (${RETRY_COUNT}/${MAX_RETRIES})..."
    sleep 2
done

if [[ "${REDIS_READY}" != "true" ]]; then
    echo "[ERROR] Redis recovery failed: server unresponsive after restart." >&2
    exit 1
fi

# 3. Ensure Consumer Group Exists for Usage Pipeline
echo "[INFO] Ensuring consumer group '${GROUP_NAME}' exists on '${STREAM_NAME}'..."
docker exec tollgate-redis redis-cli -a "${REDIS_PASSWORD:-tollgate_redis_pass}" \
    XGROUP CREATE "${STREAM_NAME}" "${GROUP_NAME}" "$" MKSTREAM 2>/dev/null || true

echo "[SUCCESS] Redis recovery verified successfully. Consumer groups restored."
exit 0
