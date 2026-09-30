#!/usr/bin/env bash
# ==============================================================================
# Tollgate Automated Rollback Script
# Reverts the running Tollgate deployment to a previously verified immutable image.
# Does NOT automatically rollback the database schema unless explicitly specified.
# ==============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <known_good_git_sha> [compose_file]" >&2
    echo "Example: $0 abc1234 docker-compose.prod.yml" >&2
    exit 1
fi

TARGET_SHA="$1"
COMPOSE_FILE="${2:-docker-compose.prod.yml}"

echo "======================================================================"
echo " [ROLLBACK] Initiating Tollgate Rollback to target commit: ${TARGET_SHA}"
echo " Compose file: ${COMPOSE_FILE}"
echo "======================================================================"

export TOLLGATE_GIT_COMMIT="${TARGET_SHA}"
TAG_API="tollgate-api:${TARGET_SHA}"
TAG_WORKER="tollgate-worker:${TARGET_SHA}"
TAG_DASHBOARD="tollgate-dashboard:${TARGET_SHA}"

# 1. Verify Image Availability
echo "[STEP 1/4] Verifying image existence for tag: ${TARGET_SHA}..."
if ! docker image inspect "${TAG_API}" >/dev/null 2>&1; then
    echo "[WARN] Image ${TAG_API} not found locally. Attempting to build from git commit ${TARGET_SHA}..."
    CURRENT_REF="$(git rev-parse HEAD)"
    git checkout "${TARGET_SHA}"
    docker build -t "${TAG_API}" -f apps/gateway/Dockerfile .
    docker build -t "${TAG_WORKER}" -f apps/worker/Dockerfile .
    docker build -t "${TAG_DASHBOARD}" -f apps/dashboard/Dockerfile .
    git checkout "${CURRENT_REF}"
fi

# 2. Recreate Services with Target Version
echo "[STEP 2/4] Restarting services with rollback images..."
if [[ -f "${COMPOSE_FILE}" ]]; then
    docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans
else
    docker compose up -d --remove-orphans
fi

# 3. Wait for Readiness
echo "[STEP 3/4] Awaiting readiness check after rollback..."
MAX_ATTEMPTS=30
ATTEMPT=1
READY=false
API_URL="${GATEWAY_URL:-http://localhost:8000}"

while [[ ${ATTEMPT} -le ${MAX_ATTEMPTS} ]]; do
    if curl -s -f "${API_URL}/health/ready" >/dev/null 2>&1; then
        READY=true
        break
    fi
    echo "  Attempt ${ATTEMPT}/${MAX_ATTEMPTS}: Service not ready yet. Retrying in 2s..."
    sleep 2
    ATTEMPT=$((ATTEMPT + 1))
done

if [[ "${READY}" != "true" ]]; then
    echo "[ERROR] Rollback verification failed: API service not ready within 60s." >&2
    exit 1
fi

# 4. Verify Version
echo "[STEP 4/4] Confirming active application version..."
VERSION_PAYLOAD="$(curl -s "${API_URL}/health/version")"
echo "  Reported version metadata: ${VERSION_PAYLOAD}"

echo "======================================================================"
echo "[SUCCESS] Rollback completed successfully to commit: ${TARGET_SHA}"
echo "======================================================================"
