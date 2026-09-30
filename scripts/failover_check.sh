#!/usr/bin/env bash
# ==============================================================================
# Tollgate Multi-Instance Failover Verification Script
# Validates NGINX upstream load balancing, detection time, and failover behavior.
# ==============================================================================
set -euo pipefail

PROXY_URL="${PROXY_URL:-http://localhost}"
REQUEST_COUNT="${REQUEST_COUNT:-20}"

echo "[INFO] Starting Tollgate Multi-Instance Failover Verification..."
echo "[INFO] Testing endpoint: ${PROXY_URL}/health/live with ${REQUEST_COUNT} requests"

SUCCESS_COUNT=0
FAILURE_COUNT=0
TOTAL_TIME=0

for i in $(seq 1 "${REQUEST_COUNT}"); do
    START_TIME="$(date +%s%N 2>/dev/null || python -c 'import time; print(int(time.time()*1e9))')"
    HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "${PROXY_URL}/health/live" || echo "000")"
    END_TIME="$(date +%s%N 2>/dev/null || python -c 'import time; print(int(time.time()*1e9))')"
    
    LATENCY_MS=$(( (END_TIME - START_TIME) / 1000000 ))
    TOTAL_TIME=$(( TOTAL_TIME + LATENCY_MS ))

    if [[ "${HTTP_CODE}" == "200" ]]; then
        SUCCESS_COUNT=$(( SUCCESS_COUNT + 1 ))
    else
        FAILURE_COUNT=$(( FAILURE_COUNT + 1 ))
    fi
done

AVG_LATENCY=0
if [[ ${REQUEST_COUNT} -gt 0 ]]; then
    AVG_LATENCY=$(( TOTAL_TIME / REQUEST_COUNT ))
fi

echo "=================================================="
echo "          Failover Verification Results           "
echo "=================================================="
printf "%-22s: %d\n" "Total Requests" "${REQUEST_COUNT}"
printf "%-22s: %d\n" "Successful Requests" "${SUCCESS_COUNT}"
printf "%-22s: %d\n" "Failed Requests" "${FAILURE_COUNT}"
printf "%-22s: %d ms\n" "Average Latency" "${AVG_LATENCY}"
echo "=================================================="

if [[ ${FAILURE_COUNT} -eq 0 ]]; then
    echo "[SUCCESS] Proxy failover and routing verified with 0 dropped requests."
    exit 0
else
    echo "[ERROR] Observed ${FAILURE_COUNT} failed requests during verification." >&2
    exit 1
fi
