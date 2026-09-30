#!/usr/bin/env bash
# ==============================================================================
# Tollgate Failure Injection Test Script
# Simulates infrastructure failures and validates system resilience.
# ==============================================================================
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
API_URL="${GATEWAY_URL:-http://localhost:8000}"
PASSED=0
FAILED=0
TOTAL=0

pass() {
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
    echo "  [PASS] $1"
}

fail() {
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
    echo "  [FAIL] $1"
}

wait_healthy() {
    local url="$1"
    local max="$2"
    local i=1
    while [[ ${i} -le ${max} ]]; do
        if curl -s -f "${url}/health/ready" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        i=$((i + 1))
    done
    return 1
}

echo "======================================================================"
echo " Tollgate Failure Injection Tests"
echo " API URL: ${API_URL}"
echo "======================================================================"
echo ""
echo "[WARNING] These tests WILL temporarily disrupt services."
echo ""

# -----------------------------------------------
# 1. Redis Failure & Recovery
# -----------------------------------------------
echo "[Test 1/4] Redis Failure & Recovery"
echo "  Pausing Redis container..."
docker pause tollgate-redis 2>/dev/null || true
sleep 3

# Gateway should report degraded/unhealthy
READY_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/health/ready" 2>/dev/null || echo "000")
if [[ "${READY_CODE}" == "503" ]]; then
    pass "Readiness probe returns 503 when Redis is down"
else
    fail "Readiness probe returned HTTP ${READY_CODE} when Redis is down (expected 503)"
fi

# Gateway liveness should still be alive
LIVE_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/health/live" 2>/dev/null || echo "000")
if [[ "${LIVE_CODE}" == "200" ]]; then
    pass "Liveness probe still returns 200 when Redis is down"
else
    fail "Liveness probe returned HTTP ${LIVE_CODE} when Redis is down (expected 200)"
fi

echo "  Unpausing Redis container..."
docker unpause tollgate-redis 2>/dev/null || true
sleep 5

# Should recover
if wait_healthy "${API_URL}" 15; then
    pass "Service recovered after Redis restored"
else
    fail "Service did not recover after Redis restored"
fi

# -----------------------------------------------
# 2. PostgreSQL Failure & Recovery
# -----------------------------------------------
echo ""
echo "[Test 2/4] PostgreSQL Failure & Recovery"
echo "  Pausing PostgreSQL container..."
docker pause tollgate-postgres 2>/dev/null || true
sleep 3

READY_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/health/ready" 2>/dev/null || echo "000")
if [[ "${READY_CODE}" == "503" ]]; then
    pass "Readiness probe returns 503 when PostgreSQL is down"
else
    fail "Readiness probe returned HTTP ${READY_CODE} when PostgreSQL is down (expected 503)"
fi

echo "  Unpausing PostgreSQL container..."
docker unpause tollgate-postgres 2>/dev/null || true
sleep 5

if wait_healthy "${API_URL}" 15; then
    pass "Service recovered after PostgreSQL restored"
else
    fail "Service did not recover after PostgreSQL restored"
fi

# -----------------------------------------------
# 3. Worker Crash & Recovery
# -----------------------------------------------
echo ""
echo "[Test 3/4] Worker Crash & Recovery"
echo "  Killing worker container..."
docker kill tollgate-worker 2>/dev/null || true
sleep 3

# Gateway should still be healthy
GW_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/health/ready" 2>/dev/null || echo "000")
if [[ "${GW_CODE}" == "200" ]]; then
    pass "Gateway remains healthy when worker is down"
else
    fail "Gateway health check returned HTTP ${GW_CODE} when worker is down"
fi

echo "  Restarting worker container..."
docker compose -f "${COMPOSE_FILE}" up -d worker 2>/dev/null || true
sleep 10

WORKER_STATUS=$(docker inspect --format='{{.State.Status}}' tollgate-worker 2>/dev/null || echo "not_found")
if [[ "${WORKER_STATUS}" == "running" ]]; then
    pass "Worker auto-recovered (status: running)"
else
    fail "Worker did not recover (status: ${WORKER_STATUS})"
fi

# -----------------------------------------------
# 4. Gateway Restart Recovery
# -----------------------------------------------
echo ""
echo "[Test 4/4] Gateway Restart Recovery"
echo "  Restarting gateway container..."
docker restart tollgate-gateway 2>/dev/null || true
sleep 5

if wait_healthy "${API_URL}" 20; then
    pass "Gateway recovered after restart"
else
    fail "Gateway did not recover after restart"
fi

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "======================================================================"
echo " Results: ${PASSED} passed, ${FAILED} failed, ${TOTAL} total"
echo "======================================================================"

if [[ ${FAILED} -gt 0 ]]; then
    echo "[WARNING] Some failure injection tests did not pass."
    exit 1
fi

echo "[SUCCESS] All failure injection tests passed."
exit 0
