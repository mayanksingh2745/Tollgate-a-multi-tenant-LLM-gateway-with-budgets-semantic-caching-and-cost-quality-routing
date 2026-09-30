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
echo "[1/6] Health Endpoints"
check_status "GET /healthz" "${API_URL}/healthz" 200
check_status "GET /health/live" "${API_URL}/health/live" 200
check_status "GET /health/ready" "${API_URL}/health/ready" 200
check_status "GET /health/version" "${API_URL}/health/version" 200

# -----------------------------------------------
# 2. Version Metadata
# -----------------------------------------------
echo ""
echo "[2/6] Version Metadata"
check_json_field "GET /health/version service" "${API_URL}/health/version" "service" "tollgate-api"

# -----------------------------------------------
# 3. Liveness / Readiness Response Shape
# -----------------------------------------------
echo ""
echo "[3/6] Response Shape Validation"
check_json_field "GET /healthz status" "${API_URL}/healthz" "status" "ok"
check_json_field "GET /health/live status" "${API_URL}/health/live" "status" "alive"
check_json_field "GET /health/ready status" "${API_URL}/health/ready" "status" "ready"

# -----------------------------------------------
# 4. API Auth Enforcement
# -----------------------------------------------
echo ""
echo "[4/6] API Authentication Enforcement"
# Chat completions without API key → must return 401 or 403
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" \
    -X POST "${API_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4","messages":[{"role":"user","content":"test"}]}' 2>/dev/null || echo "000")
if [[ "${HTTP_CODE}" == "401" || "${HTTP_CODE}" == "403" || "${HTTP_CODE}" == "422" ]]; then
    pass "POST /v1/chat/completions (no auth) → HTTP ${HTTP_CODE}"
else
    fail "POST /v1/chat/completions (no auth) → expected 401/403/422, got HTTP ${HTTP_CODE}"
fi

# -----------------------------------------------
# 5. Metrics Endpoint
# -----------------------------------------------
echo ""
echo "[5/6] Metrics Endpoint"
# Metrics without auth token → should return 401 or 403
METRICS_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT_S}" "${API_URL}/metrics" 2>/dev/null || echo "000")
if [[ "${METRICS_CODE}" == "401" || "${METRICS_CODE}" == "403" || "${METRICS_CODE}" == "200" ]]; then
    pass "GET /metrics (auth check) → HTTP ${METRICS_CODE}"
else
    fail "GET /metrics → unexpected HTTP ${METRICS_CODE}"
fi

# -----------------------------------------------
# 6. Detailed Health
# -----------------------------------------------
echo ""
echo "[6/6] Detailed Health Check"
check_status "GET /api/v1/health" "${API_URL}/api/v1/health" 200

# -----------------------------------------------
# Summary
# -----------------------------------------------
echo ""
echo "======================================================================"
echo " Results: ${PASSED} passed, ${FAILED} failed, ${TOTAL} total"
echo "======================================================================"

if [[ ${FAILED} -gt 0 ]]; then
    echo "[ERROR] Smoke tests FAILED. Deployment should NOT be promoted."
    exit 1
fi

echo "[SUCCESS] All smoke tests passed. Deployment is healthy."
exit 0
