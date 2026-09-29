import logging

from fastapi import Depends, HTTPException, Request, status
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.ratelimit.limiter import (
    RateLimitBackendError,
    RateLimitResult,
    rate_limiter,
)

logger = logging.getLogger("tollgate.ratelimit")


class RateLimitExceeded(Exception):
    """Exception raised when an authenticated client exceeds their allocated token bucket limit."""

    def __init__(self, result: RateLimitResult):
        self.result = result
        super().__init__(f"Rate limit exceeded for key {result.key}")


async def rate_limit_dependency(
    request: Request,
    ctx: AuthenticatedContext = Depends(get_current_api_key),
) -> RateLimitResult:
    """
    FastAPI dependency for distributed rate limiting.
    Checks token bucket capacity against Redis before allowing request execution.
    Attaches rate limit result to request.state for downstream header injection.
    """
    try:
        result = await rate_limiter.check(
            api_key_id=ctx.api_key_id,
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
        )
    except RateLimitBackendError as e:
        logger.error("Rate limiter backend failure: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "message": "Rate limiter backend is temporarily unavailable.",
                    "type": "service_unavailable",
                    "code": "rate_limiter_unavailable",
                }
            },
        ) from e

    if not result.allowed:
        logger.warning(
            "Rate limit exceeded for API key %s (retry_after=%.2fs)",
            ctx.api_key_id,
            result.retry_after,
        )
        raise RateLimitExceeded(result)

    # Store in request.state so routes can easily inspect and inject rate limit headers
    request.state.rate_limit_result = result
    return result
