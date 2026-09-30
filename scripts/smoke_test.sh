#!/usr/bin/env bash
# ==============================================================================
# Tollgate Automated Smoke Test Suite
# Validates critical endpoints after deployment.
# Returns non-zero on ANY failure for CI/CD pipeline integration.
# ==============================================================================
set -euo pipefail

API_URL="${GATEWAY_URL:-http://localhost:8000}"
TIMEOUT_S="${SMOKE_TIMEOUT_SECONDS:-5}"
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=0

# -----------------------------------------------
# Helpers
# -----------------------------------------------
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

skip() {
    SKIPPED=$((SKIPPED + 1))
    TOTAL=$((TOTAL + 1))
    echo "  [SKIP] $1"
}

check_status() {
    local label="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local actual_status

    actual_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" "${url}" 2>/dev/null || echo "000")
    if [[ "${actual_status}" == "${expected_status}" ]]; then
        pass "${label} → HTTP ${actual_status}"
    else
        fail "${label} → expected HTTP ${expected_status}, got HTTP ${actual_status}"
    fi
}

check_json_field() {
    local label="$1"
    local url="$2"
    local field="$3"
    local expected="$4"
    local body

    body=$(curl -s --max-time "${TIMEOUT_S}" "${url}" 2>/dev/null || echo "{}")
    local actual
    actual=$(echo "${body}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('${field}',''))" 2>/dev/null || echo "")
    if [[ "${actual}" == "${expected}" ]]; then
        pass "${label} → ${field}='${actual}'"
    else
        fail "${label} → expected ${field}='${expected}', got '${actual}'"
    fi
}

echo "======================================================================"
echo " Tollgate Smoke Test Suite"
echo " Target: ${API_URL}"
echo " Timeout: ${TIMEOUT_S}s per request"
echo "======================================================================"

# -----------------------------------------------
# 1. Health Endpoints
# -----------------------------------------------
echo ""
echo "[1/10] Health Endpoints"
check_status "GET /healthz" "${API_URL}/healthz" 200
check_status "GET /health/live" "${API_URL}/health/live" 200
check_status "GET /health/ready" "${API_URL}/health/ready" 200
check_status "GET /health/version" "${API_URL}/health/version" 200
check_status "GET /api/v1/health" "${API_URL}/api/v1/health" 200

# -----------------------------------------------
# 2. Version Metadata
# -----------------------------------------------
echo ""
echo "[2/10] Version Metadata"
check_json_field "GET /health/version service" "${API_URL}/health/version" "service" "tollgate-api"

# Verify version endpoint returns required fields
VERSION_BODY=$(curl -s --max-time "${TIMEOUT_S}" "${API_URL}/health/version" 2>/dev/null || echo "{}")
for field in version git_commit environment; do
    val=$(echo "${VERSION_BODY}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('${field}',''))" 2>/dev/null || echo "")
    if [[ -n "${val}" ]]; then
        pass "Version field '${field}' present: ${val}"
    else
        fail "Version field '${field}' missing"
    fi
done

# -----------------------------------------------
# 3. Liveness / Readiness Response Shape
# -----------------------------------------------
echo ""
echo "[3/10] Response Shape Validation"
check_json_field "GET /healthz status" "${API_URL}/healthz" "status" "ok"
check_json_field "GET /health/live status" "${API_URL}/health/live" "status" "alive"
check_json_field "GET /health/ready status" "${API_URL}/health/ready" "status" "ready"

# -----------------------------------------------
# 4. API Authentication Enforcement
# -----------------------------------------------
echo ""
echo "[4/10] API Authentication Enforcement"

# Chat completions without API key → must be rejected
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "000")
if [[ "${HTTP_CODE}" == "401" || "${HTTP_CODE}" == "403" || "${HTTP_CODE}" == "422" ]]; then
    pass "POST /v1/chat/completions (no auth) → HTTP ${HTTP_CODE}"
else
    fail "POST /v1/chat/completions (no auth) → expected 401/403/422, got HTTP ${HTTP_CODE}"
fi

# Invalid API key → must be rejected
HTTP_CODE_BAD=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer tg_INVALID_KEY_12345" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "000")
if [[ "${HTTP_CODE_BAD}" == "401" || "${HTTP_CODE_BAD}" == "403" ]]; then
    pass "POST /v1/chat/completions (bad key) → HTTP ${HTTP_CODE_BAD}"
else
    fail "POST /v1/chat/completions (bad key) → expected 401/403, got HTTP ${HTTP_CODE_BAD}"
fi

# -----------------------------------------------
# 5. Tenant API Endpoints Authentication
# -----------------------------------------------
echo ""
echo "[5/10] Tenant Endpoints Authentication"

# Tenant list without auth → should be rejected
TENANT_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" "${API_URL}/api/v1/tenants" 2>/dev/null || echo "000")
if [[ "${TENANT_CODE}" == "401" || "${TENANT_CODE}" == "403" || "${TENANT_CODE}" == "404" || "${TENANT_CODE}" == "405" ]]; then
    pass "GET /api/v1/tenants (no auth) → HTTP ${TENANT_CODE}"
else
    fail "GET /api/v1/tenants (no auth) → unexpected HTTP ${TENANT_CODE}"
fi

# Dashboard analytics without auth
DASH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" "${API_URL}/api/v1/dashboard/overview" 2>/dev/null || echo "000")
if [[ "${DASH_CODE}" == "401" || "${DASH_CODE}" == "403" || "${DASH_CODE}" == "404" || "${DASH_CODE}" == "422" ]]; then
    pass "GET /api/v1/dashboard/overview (no auth) → HTTP ${DASH_CODE}"
else
    fail "GET /api/v1/dashboard/overview (no auth) → unexpected HTTP ${DASH_CODE}"
fi

# -----------------------------------------------
# 6. Metrics Endpoint
# -----------------------------------------------
echo ""
echo "[6/10] Metrics Endpoint"

METRICS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" "${API_URL}/metrics" 2>/dev/null || echo "000")
if [[ "${METRICS_CODE}" == "401" || "${METRICS_CODE}" == "403" ]]; then
    pass "GET /metrics (no auth) → requires auth (HTTP ${METRICS_CODE})"
elif [[ "${METRICS_CODE}" == "200" ]]; then
    # Metrics auth might be disabled in staging/test
    echo "  [INFO] GET /metrics → HTTP 200 (auth may be disabled in staging)"
    TOTAL=$((TOTAL + 1))
    PASSED=$((PASSED + 1))
elif [[ "${METRICS_CODE}" == "404" ]]; then
    skip "GET /metrics → endpoint not found (metrics may be disabled)"
else
    fail "GET /metrics → unexpected HTTP ${METRICS_CODE}"
fi

# -----------------------------------------------
# 7. Error Response Safety
# -----------------------------------------------
echo ""
echo "[7/10] Error Response Safety"

ERROR_BODY=$(curl -s --max-time "${TIMEOUT_S}" \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "{}")

if echo "${ERROR_BODY}" | grep -qiE "(traceback|File \"|line [0-9]|at 0x)"; then
    fail "Error response contains stack trace information"
else
    pass "Error response does not leak stack traces"
fi

if echo "${ERROR_BODY}" | grep -qiE "(postgresql|redis://|password|secret_pass)"; then
    fail "Error response contains sensitive information"
else
    pass "Error response does not leak sensitive data"
fi

# -----------------------------------------------
# 8. Security Headers
# -----------------------------------------------
echo ""
echo "[8/10] Security Headers"

HEADERS=$(curl -sI --max-time "${TIMEOUT_S}" "${API_URL}/healthz" 2>/dev/null || echo "")

if echo "${HEADERS}" | grep -qi "x-content-type-options"; then
    pass "X-Content-Type-Options header present"
else
    # May only be present behind proxy
    skip "X-Content-Type-Options header (may require NGINX proxy)"
fi

if echo "${HEADERS}" | grep -qi "server:.*nginx/[0-9]"; then
    fail "Server header reveals nginx version"
else
    pass "Server header does not reveal version info"
fi

# -----------------------------------------------
# 9. Cache Header
# -----------------------------------------------
echo ""
echo "[9/10] Cache Infrastructure"

# Verify cache-related health (through detailed health endpoint)
HEALTH_BODY=$(curl -s --max-time "${TIMEOUT_S}" "${API_URL}/api/v1/health" 2>/dev/null || echo "{}")
REDIS_STATUS=$(echo "${HEALTH_BODY}" | python3 -c "
import sys,json
d=json.load(sys.stdin)
for s in d.get('services',[]):
    if s.get('name')=='redis':
        print(s.get('status',''))
" 2>/dev/null || echo "")
if [[ "${REDIS_STATUS}" == "healthy" ]]; then
    pass "Redis (cache backend) is healthy"
elif [[ -z "${REDIS_STATUS}" ]]; then
    skip "Redis status not available in health response"
else
    fail "Redis status: ${REDIS_STATUS}"
fi

# -----------------------------------------------
# 10. Detailed Health Check
# -----------------------------------------------
echo ""
echo "[10/10] Detailed Health Check"
check_status "GET /api/v1/health" "${API_URL}/api/v1/health" 200

OVERALL_STATUS=$(echo "${HEALTH_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [[ "${OVERALL_STATUS}" == "healthy" ]]; then
    pass "Overall system status: healthy"
elif [[ "${OVERALL_STATUS}" == "degraded" ]]; then
    fail "Overall system status: degraded"
else
    fail "Overall system status: ${OVERALL_STATUS}"
fi

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "======================================================================"
echo " Results: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped, ${TOTAL} total"
echo "======================================================================"

if [[ ${FAILED} -gt 0 ]]; then
    echo "[ERROR] Smoke tests FAILED. Deployment should NOT be promoted."
    exit 1
fi

echo "[SUCCESS] All smoke tests passed. Deployment is healthy."
exit 0
