#!/usr/bin/env bash
# ==============================================================================
# Tollgate Security Validation Script
# Final pre-production security checks. Run AFTER deployment, BEFORE traffic.
# ==============================================================================
set -euo pipefail

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
echo " Tollgate Security Validation"
echo " Target: ${API_URL}"
echo "======================================================================"

# -----------------------------------------------
# 1. API Key Enforcement
# -----------------------------------------------
echo ""
echo "[1/8] API Key Enforcement"

# Unauthenticated chat completions must be rejected
CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "000")
if [[ "${CODE}" == "401" || "${CODE}" == "403" || "${CODE}" == "422" ]]; then
    pass "Chat endpoint rejects unauthenticated requests (HTTP ${CODE})"
else
    fail "Chat endpoint returned HTTP ${CODE} without authentication"
fi

# -----------------------------------------------
# 2. Error Message Safety
# -----------------------------------------------
echo ""
echo "[2/8] Error Message Safety"

BODY=$(curl -s --max-time 5 \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "{}")

# Should NOT contain stack traces
if echo "${BODY}" | grep -qiE "(traceback|File \"|line [0-9]|at 0x)"; then
    fail "Error response contains stack trace information"
else
    pass "Error response does not leak stack traces"
fi

# Should NOT contain database connection strings
if echo "${BODY}" | grep -qiE "(postgresql|redis://|password|secret)"; then
    fail "Error response contains sensitive information"
else
    pass "Error response does not leak sensitive data"
fi

# -----------------------------------------------
# 3. Security Headers
# -----------------------------------------------
echo ""
echo "[3/8] Security Headers"

HEADERS=$(curl -sI --max-time 5 "${API_URL}/healthz" 2>/dev/null || echo "")

# X-Content-Type-Options
if echo "${HEADERS}" | grep -qi "x-content-type-options.*nosniff"; then
    pass "X-Content-Type-Options: nosniff present"
else
    fail "X-Content-Type-Options header missing"
fi

# X-Frame-Options
if echo "${HEADERS}" | grep -qi "x-frame-options"; then
    pass "X-Frame-Options header present"
else
    fail "X-Frame-Options header missing"
fi

# Server header should not reveal version
if echo "${HEADERS}" | grep -qi "server:.*nginx/[0-9]"; then
    fail "Server header reveals nginx version"
else
    pass "Server header does not reveal version"
fi

# -----------------------------------------------
# 4. Debug Endpoints Disabled
# -----------------------------------------------
echo ""
echo "[4/8] Debug Endpoints"

# /docs should be disabled in production
DOCS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/docs" 2>/dev/null || echo "000")
if [[ "${DOCS_CODE}" == "404" || "${DOCS_CODE}" == "403" ]]; then
    pass "API docs disabled in production (HTTP ${DOCS_CODE})"
else
    fail "API docs may be enabled (HTTP ${DOCS_CODE})"
fi

# -----------------------------------------------
# 5. Container Security
# -----------------------------------------------
echo ""
echo "[5/8] Container Security"

for c in tollgate-gateway tollgate-worker; do
    EXISTS=$(docker inspect "${c}" 2>/dev/null && echo "yes" || echo "no")
    if [[ "${EXISTS}" == "no" ]]; then
        fail "${c} container not found"
        continue
    fi

    USER=$(docker inspect --format='{{.Config.User}}' "${c}" 2>/dev/null || echo "")
    if [[ -n "${USER}" && "${USER}" != "root" && "${USER}" != "0" ]]; then
        pass "${c} runs as non-root (${USER})"
    else
        fail "${c} runs as root"
    fi

    # Check read-only root filesystem
    READONLY=$(docker inspect --format='{{.HostConfig.ReadonlyRootfs}}' "${c}" 2>/dev/null || echo "false")
    if [[ "${READONLY}" == "true" ]]; then
        pass "${c} has read-only root filesystem"
    else
        # Not enforced; just a recommendation
        echo "  [INFO] ${c} does not have read-only root filesystem (recommended)"
    fi
done

# -----------------------------------------------
# 6. Database Port Exposure
# -----------------------------------------------
echo ""
echo "[6/8] Network Exposure"

for c in tollgate-postgres tollgate-redis; do
    EXISTS=$(docker inspect "${c}" 2>/dev/null && echo "yes" || echo "no")
    if [[ "${EXISTS}" == "no" ]]; then
        echo "  [SKIP] ${c} container not found"
        continue
    fi

    PORTS=$(docker inspect --format='{{json .NetworkSettings.Ports}}' "${c}" 2>/dev/null || echo "{}")
    if echo "${PORTS}" | grep -q '"HostPort"'; then
        fail "${c} has host-published ports (SHOULD NOT in production)"
    else
        pass "${c} has no host-published ports"
    fi
done

# -----------------------------------------------
# 7. Metrics Authentication
# -----------------------------------------------
echo ""
echo "[7/8] Metrics Authentication"

METRICS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${API_URL}/metrics" 2>/dev/null || echo "000")
if [[ "${METRICS_CODE}" == "401" || "${METRICS_CODE}" == "403" ]]; then
    pass "Metrics endpoint requires authentication (HTTP ${METRICS_CODE})"
elif [[ "${METRICS_CODE}" == "200" ]]; then
    fail "Metrics endpoint is publicly accessible without auth"
else
    echo "  [INFO] Metrics endpoint returned HTTP ${METRICS_CODE}"
fi

# -----------------------------------------------
# 8. Environment Validation
# -----------------------------------------------
echo ""
echo "[8/8] Environment Validation"

ENV_VAL=$(curl -s --max-time 5 "${API_URL}/health/version" 2>/dev/null | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('environment',''))" 2>/dev/null || echo "")
if [[ "${ENV_VAL}" == "production" ]]; then
    pass "Environment set to 'production'"
elif [[ "${ENV_VAL}" == "staging" ]]; then
    pass "Environment set to 'staging' (acceptable for staging validation)"
else
    fail "Environment is '${ENV_VAL}', expected 'production' or 'staging'"
fi

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "======================================================================"
echo " Results: ${PASSED} passed, ${FAILED} failed, ${TOTAL} total"
echo "======================================================================"

if [[ ${FAILED} -gt 0 ]]; then
    echo "[ERROR] Security validation FAILED. Do NOT promote this deployment."
    exit 1
fi

echo "[SUCCESS] Security validation passed."
exit 0
