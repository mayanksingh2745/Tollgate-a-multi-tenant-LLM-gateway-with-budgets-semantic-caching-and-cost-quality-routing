#!/usr/bin/env bash
# ==============================================================================
# Tollgate Deployment Validation Script
# Performs end-to-end validation of a deployed Tollgate stack.
# Covers: container health, networking, database, Redis, logging, security.
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

echo "======================================================================"
echo " Tollgate Deployment Validation"
echo " Compose: ${COMPOSE_FILE}"
echo " API URL: ${API_URL}"
echo "======================================================================"

# -----------------------------------------------
# 1. Container Status
# -----------------------------------------------
echo ""
echo "[1/7] Container Status"
CONTAINERS=(tollgate-gateway tollgate-worker tollgate-postgres tollgate-redis tollgate-proxy)
for c in "${CONTAINERS[@]}"; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "${c}" 2>/dev/null || echo "not_found")
    if [[ "${STATUS}" == "running" ]]; then
        pass "${c} → running"
    else
        fail "${c} → ${STATUS}"
    fi
done

# -----------------------------------------------
# 2. Container Security
# -----------------------------------------------
echo ""
echo "[2/7] Container Security"
for c in tollgate-gateway tollgate-worker; do
    USER=$(docker inspect --format='{{.Config.User}}' "${c}" 2>/dev/null || echo "")
    if [[ -n "${USER}" && "${USER}" != "root" && "${USER}" != "0" ]]; then
        pass "${c} runs as non-root (user: ${USER})"
    else
        fail "${c} runs as root or user not set (user: '${USER}')"
    fi
done

# Check no-new-privileges
for c in tollgate-gateway tollgate-worker; do
    NO_NEW_PRIVS=$(docker inspect --format='{{.HostConfig.SecurityOpt}}' "${c}" 2>/dev/null || echo "")
    if echo "${NO_NEW_PRIVS}" | grep -q "no-new-privileges"; then
        pass "${c} has no-new-privileges"
    else
        fail "${c} missing no-new-privileges (got: ${NO_NEW_PRIVS})"
    fi
done

# -----------------------------------------------
# 3. Network Isolation
# -----------------------------------------------
echo ""
echo "[3/7] Network Isolation"
# Postgres should NOT have host-published ports in production
PG_PORTS=$(docker inspect --format='{{json .NetworkSettings.Ports}}' tollgate-postgres 2>/dev/null || echo "{}")
if echo "${PG_PORTS}" | grep -q '"HostPort"'; then
    fail "PostgreSQL has host-published ports (security risk)"
else
    pass "PostgreSQL has no host-published ports"
fi

# Redis should NOT have host-published ports in production
REDIS_PORTS=$(docker inspect --format='{{json .NetworkSettings.Ports}}' tollgate-redis 2>/dev/null || echo "{}")
if echo "${REDIS_PORTS}" | grep -q '"HostPort"'; then
    fail "Redis has host-published ports (security risk)"
else
    pass "Redis has no host-published ports"
fi

# -----------------------------------------------
# 4. Database Connectivity
# -----------------------------------------------
echo ""
echo "[4/7] Database Connectivity"
DB_READY=$(curl -s --max-time 5 "${API_URL}/health/ready" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('database',''))" 2>/dev/null || echo "")
if [[ "${DB_READY}" == "ok" ]]; then
    pass "Database connectivity via /health/ready → ok"
else
    fail "Database connectivity via /health/ready → '${DB_READY}'"
fi

# -----------------------------------------------
# 5. Redis Connectivity
# -----------------------------------------------
echo ""
echo "[5/7] Redis Connectivity"
REDIS_READY=$(curl -s --max-time 5 "${API_URL}/health/ready" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('redis',''))" 2>/dev/null || echo "")
if [[ "${REDIS_READY}" == "ok" ]]; then
    pass "Redis connectivity via /health/ready → ok"
else
    fail "Redis connectivity via /health/ready → '${REDIS_READY}'"
fi

# -----------------------------------------------
# 6. Version Metadata
# -----------------------------------------------
echo ""
echo "[6/7] Version Metadata"
VERSION_JSON=$(curl -s --max-time 5 "${API_URL}/health/version" 2>/dev/null || echo "{}")
VER=$(echo "${VERSION_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null || echo "")
COMMIT=$(echo "${VERSION_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('git_commit',''))" 2>/dev/null || echo "")
ENV_STR=$(echo "${VERSION_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('environment',''))" 2>/dev/null || echo "")

if [[ -n "${VER}" ]]; then
    pass "Version reported: ${VER}"
else
    fail "Version not reported"
fi

if [[ -n "${COMMIT}" && "${COMMIT}" != "unknown" ]]; then
    pass "Git commit reported: ${COMMIT}"
else
    fail "Git commit not reported or is 'unknown'"
fi

if [[ "${ENV_STR}" == "production" ]]; then
    pass "Environment: production"
else
    fail "Environment is '${ENV_STR}', expected 'production'"
fi

# -----------------------------------------------
# 7. Log Drivers
# -----------------------------------------------
echo ""
echo "[7/7] Logging Configuration"
for c in tollgate-gateway tollgate-worker tollgate-postgres tollgate-redis; do
    LOG_DRIVER=$(docker inspect --format='{{.HostConfig.LogConfig.Type}}' "${c}" 2>/dev/null || echo "unknown")
    if [[ "${LOG_DRIVER}" == "json-file" ]]; then
        pass "${c} log driver: json-file"
    else
        fail "${c} log driver: ${LOG_DRIVER} (expected json-file)"
    fi
done

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "======================================================================"
echo " Results: ${PASSED} passed, ${FAILED} failed, ${TOTAL} total"
echo "======================================================================"

if [[ ${FAILED} -gt 0 ]]; then
    echo "[WARNING] Deployment validation has ${FAILED} failures."
    exit 1
fi

echo "[SUCCESS] Deployment validation passed."
exit 0
