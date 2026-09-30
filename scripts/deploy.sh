#!/usr/bin/env bash
# ==============================================================================
# Tollgate Production Deployment Script
# Deterministically builds, migrates, deploys, and verifies the Tollgate stack.
# ==============================================================================
set -euo pipefail

ENVIRONMENT="${ENVIRONMENT:-production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

# 1. Identify Release Version
GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo "prod-$(date +%s)")"
export TOLLGATE_VERSION="${TOLLGATE_VERSION:-1.0.0}"
export TOLLGATE_GIT_COMMIT="${GIT_COMMIT}"

echo "======================================================================"
echo " Starting Tollgate Deployment: version=${TOLLGATE_VERSION} commit=${TOLLGATE_GIT_COMMIT}"
echo " Environment: ${ENVIRONMENT}"
echo " Compose file: ${COMPOSE_FILE}"
echo "======================================================================"

# 2. Validate Configuration
echo "[STEP 1/7] Validating deployment configuration..."
if [[ "${ENVIRONMENT}" == "production" ]]; then
    if [[ -z "${DATABASE_URL:-}" ]] && [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
        echo "[ERROR] Missing DATABASE_URL / POSTGRES_PASSWORD in production environment." >&2
        exit 1
    fi
    if [[ "${POSTGRES_PASSWORD:-}" == "tollgate_secret_pass" ]]; then
        echo "[ERROR] Insecure default POSTGRES_PASSWORD is forbidden in production." >&2
        exit 1
    fi
fi

# 3. Build Immutable Production Images
echo "[STEP 2/7] Building immutable production container images..."
TAG_API="tollgate-api:${GIT_COMMIT}"
TAG_WORKER="tollgate-worker:${GIT_COMMIT}"
TAG_DASHBOARD="tollgate-dashboard:${GIT_COMMIT}"

docker build -t "${TAG_API}" -f apps/gateway/Dockerfile .
docker build -t "${TAG_WORKER}" -f apps/worker/Dockerfile .
docker build -t "${TAG_DASHBOARD}" -f apps/dashboard/Dockerfile .

# 4. Verify Database Connectivity & Run Migrations
echo "[STEP 3/7] Running database migrations (alembic upgrade head)..."
if command -v python >/dev/null 2>&1; then
    python -m alembic upgrade head
else
    # Run migrations inside a temporary container
    docker run --rm \
        --network tollgate-backend \
        -e DATABASE_URL="${DATABASE_URL}" \
        "${TAG_API}" \
        python -m alembic upgrade head
fi

# 5. Start/Recreate Services
echo "[STEP 4/7] Recreating container services via Docker Compose..."
if [[ -f "${COMPOSE_FILE}" ]]; then
    docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans
else
    docker compose up -d --remove-orphans
fi

# 6. Wait for Readiness
echo "[STEP 5/7] Waiting for API readiness check (/health/ready)..."
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
    echo "[ERROR] Deployment failed: API service failed readiness probe within 60s." >&2
    exit 1
fi
echo "[OK] API is healthy and ready to receive traffic."

# 7. Verify Version Endpoint
echo "[STEP 6/7] Verifying deployed application version..."
VERSION_PAYLOAD="$(curl -s "${API_URL}/health/version")"
echo "  Reported version metadata: ${VERSION_PAYLOAD}"

# 8. Smoke Tests
echo "[STEP 7/7] Running post-deployment smoke tests..."
HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/healthz")"
if [[ "${HTTP_STATUS}" -ne 200 ]]; then
    echo "[ERROR] Smoke test failed: /healthz returned HTTP ${HTTP_STATUS}" >&2
    exit 1
fi

echo "======================================================================"
echo "[SUCCESS] Tollgate deployment complete: ${TAG_API}"
echo "======================================================================"
