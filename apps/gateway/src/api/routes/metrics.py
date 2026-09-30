"""
Prometheus Metrics Route for Tollgate LLM Gateway.

Exposes /metrics in standard Prometheus text exposition format.
Restricted by default with bearer token or header verification to prevent
public accessibility. Does not leak prompts, responses, keys, or secrets.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status
from gateway.src.config import settings
from tollgate_core.observability import CONTENT_TYPE_LATEST, export_metrics

router = APIRouter(tags=["Observability"])


@router.get(
    "/metrics",
    summary="Prometheus Metrics Endpoint",
    description="Exposes aggregated, bounded Prometheus metrics for scraping.",
    include_in_schema=False,
)
async def get_prometheus_metrics(request: Request) -> Response:
    """
    Exposes gateway and subsystem metrics in Prometheus text format.
    Guarded by token authentication when metrics_auth_enabled is True.
    """
    if not settings.metrics_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics collection is disabled",
        )

    if settings.metrics_auth_enabled:
        auth_header = request.headers.get("Authorization", "")
        token_header = request.headers.get("X-Metrics-Token", "")

        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif token_header:
            token = token_header.strip()

        expected_token = settings.metrics_token
        if not token or token != expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to Prometheus metrics",
                headers={"WWW-Authenticate": "Bearer"},
            )

    try:
        metrics_bytes = export_metrics()
        return Response(content=metrics_bytes, media_type=CONTENT_TYPE_LATEST)
    except Exception as exc:
        # Metrics endpoint failure must never break gateway operation
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate metrics.",
        ) from exc
