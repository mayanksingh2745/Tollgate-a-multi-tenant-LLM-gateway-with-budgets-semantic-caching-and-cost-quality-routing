"""
Internal Operator Diagnostics Route for Tollgate LLM Gateway.

Provides /internal/provider-health for operators to inspect real-time circuit
breaker state, failure counts, cooldown timers, and legacy health monitor status.
Restricted by token authentication (matching metrics token or admin authorization).
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status
from gateway.src.config import settings
from gateway.src.reliability.circuit_breaker import circuit_breaker_registry
from gateway.src.reliability.health import health_tracker

router = APIRouter(prefix="/internal", tags=["Internal Diagnostics"])


@router.get(
    "/provider-health",
    summary="Provider Health and Circuit Breaker Diagnostics",
    description="Returns real-time status of all provider circuits, failure windows, and health monitors.",
)
async def get_provider_health(request: Request) -> Dict[str, Any]:
    """
    Operator-facing diagnostic endpoint for inspecting provider circuits.
    Guarded when metrics_auth_enabled is True.
    """
    if settings.metrics_auth_enabled:
        auth_header = request.headers.get("Authorization", "")
        token_header = request.headers.get("X-Admin-Token", "") or request.headers.get(
            "X-Metrics-Token", ""
        )

        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif token_header:
            token = token_header.strip()

        expected_token = settings.metrics_token
        if not token or token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to provider health diagnostics",
                headers={"WWW-Authenticate": "Bearer"},
            )

    circuit_statuses = circuit_breaker_registry.get_all_status()

    # Determine provider-level health
    provider_statuses = {}
    for p_name, state in health_tracker._states.items():
        provider_statuses[p_name] = {
            "is_healthy": state.is_healthy,
            "unhealthy_since": state.unhealthy_since,
        }

    # Calculate overall health
    any_open = any(
        c.get("state") == "open" for c in circuit_statuses.values()
    )
    all_open = bool(circuit_statuses) and all(
        c.get("state") == "open" for c in circuit_statuses.values()
    )

    if all_open:
        overall_status = "unhealthy"
    elif any_open:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "circuit_breaker_enabled": circuit_breaker_registry.enabled,
        "circuits": circuit_statuses,
        "providers": provider_statuses,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
