import asyncio
import logging
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple
from uuid import UUID

import redis.asyncio as aioredis
from gateway.src.config import settings
from gateway.src.ratelimit.lua import TOKEN_BUCKET_LUA
from gateway.src.redis import get_redis_client

logger = logging.getLogger("tollgate.ratelimit")


class RateLimitBackendError(Exception):
    """Raised when the rate limit backend experiences a critical failure and fail-closed is active."""

    pass


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_after: float
    retry_after: float
    key: str

    @property
    def headers(self) -> Dict[str, str]:
        hdrs = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(math.ceil(self.reset_after)),
        }
        if not self.allowed:
            hdrs["Retry-After"] = str(max(1, math.ceil(self.retry_after)))
        return hdrs


class BaseRateLimitBackend(ABC):
    @abstractmethod
    async def consume(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        cost: int = 1,
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """Atomically refill tokens and attempt to consume `cost` tokens."""
        pass


class RedisRateLimitBackend(BaseRateLimitBackend):
    def __init__(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        timeout_seconds: Optional[float] = None,
        failure_mode: Optional[str] = None,
    ):
        self._client = redis_client
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.rate_limit_redis_timeout_seconds
        )
        self.failure_mode = (
            failure_mode if failure_mode is not None else settings.rate_limit_redis_failure_mode
        )
        self._script_sha: Optional[str] = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is not None:
            return self._client
        return await get_redis_client()

    async def consume(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        cost: int = 1,
        now: Optional[float] = None,
    ) -> RateLimitResult:
        current_time = now if now is not None else time.time()
        client = await self._get_client()

        try:
            # Execute Lua script atomically within timeout
            coro = client.eval(
                TOKEN_BUCKET_LUA,
                1,
                key,
                str(capacity),
                str(refill_rate),
                str(cost),
                str(current_time),
            )
            raw_result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)

            allowed_flag, tokens_str, retry_after_str, reset_after_str = raw_result
            allowed = bool(int(allowed_flag))
            remaining = int(math.floor(float(tokens_str)))
            retry_after = float(retry_after_str)
            reset_after = float(reset_after_str)

            return RateLimitResult(
                allowed=allowed,
                limit=capacity,
                remaining=remaining,
                reset_after=reset_after,
                retry_after=retry_after,
                key=key,
            )

        except (asyncio.TimeoutError, aioredis.RedisError, ConnectionError, OSError) as exc:
            logger.warning(
                "Redis rate limit check failed for key %s: %s (failure_mode=%s)",
                key,
                exc,
                self.failure_mode,
            )
            if self.failure_mode == "open":
                # Fail-open: allow request to proceed during Redis outage
                return RateLimitResult(
                    allowed=True,
                    limit=capacity,
                    remaining=capacity,
                    reset_after=0.0,
                    retry_after=0.0,
                    key=key,
                )
            else:
                # Fail-closed: reject request to protect upstream resources
                raise RateLimitBackendError(f"Rate limiter service unavailable: {exc}") from exc


class InMemoryRateLimitBackend(BaseRateLimitBackend):
    """
    Deterministic in-memory rate limit backend replicating Redis token bucket Lua logic.
    Ideal for unit tests and local environments without Redis.
    """

    def __init__(self, now_func: Optional[Callable[[], float]] = None):
        self._buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_updated)
        self._lock = asyncio.Lock()
        self._now_func = now_func or time.time

    async def consume(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        cost: int = 1,
        now: Optional[float] = None,
    ) -> RateLimitResult:
        current_time = now if now is not None else self._now_func()

        async with self._lock:
            if key not in self._buckets:
                tokens = float(capacity)
                last_updated = current_time
            else:
                tokens, last_updated = self._buckets[key]
                elapsed = max(0.0, current_time - last_updated)
                tokens = min(float(capacity), tokens + (elapsed * refill_rate))
                last_updated = current_time

            allowed = tokens >= cost
            if allowed:
                tokens -= cost
                retry_after = 0.0
            else:
                deficit = cost - tokens
                retry_after = deficit / refill_rate if refill_rate > 0 else 60.0

            missing = float(capacity) - tokens
            reset_after = missing / refill_rate if missing > 0 and refill_rate > 0 else 0.0

            self._buckets[key] = (tokens, last_updated)

            return RateLimitResult(
                allowed=allowed,
                limit=capacity,
                remaining=int(math.floor(tokens)),
                reset_after=reset_after,
                retry_after=retry_after,
                key=key,
            )

    def reset(self) -> None:
        self._buckets.clear()


class RateLimiter:
    """
    High-level token-bucket rate limiter.
    Coordinates key generation, scope mapping, and backend delegation.
    """

    def __init__(
        self,
        backend: Optional[BaseRateLimitBackend] = None,
        enabled: Optional[bool] = None,
        requests_per_second: Optional[float] = None,
        burst: Optional[int] = None,
        prefix: Optional[str] = None,
    ):
        self.backend = backend or RedisRateLimitBackend()
        self.enabled = enabled if enabled is not None else settings.rate_limit_enabled
        self.requests_per_second = (
            requests_per_second
            if requests_per_second is not None
            else settings.rate_limit_requests_per_second
        )
        self.burst = burst if burst is not None else settings.rate_limit_burst
        self.prefix = prefix or settings.rate_limit_redis_prefix

    def build_key(
        self,
        api_key_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
    ) -> str:
        """
        Build isolated Redis key.
        Default scope: authenticated API key ID.
        """
        if api_key_id:
            return f"{self.prefix}:apikey:{api_key_id}"
        if project_id:
            return f"{self.prefix}:project:{project_id}"
        if tenant_id:
            return f"{self.prefix}:tenant:{tenant_id}"
        return f"{self.prefix}:global"

    async def check(
        self,
        api_key_id: Optional[UUID] = None,
        tenant_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        cost: int = 1,
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """
        Check rate limit and consume token if permitted.
        If rate limiting is globally disabled, always allow.
        """
        key = self.build_key(api_key_id=api_key_id, tenant_id=tenant_id, project_id=project_id)

        if not self.enabled:
            return RateLimitResult(
                allowed=True,
                limit=self.burst,
                remaining=self.burst,
                reset_after=0.0,
                retry_after=0.0,
                key=key,
            )

        return await self.backend.consume(
            key=key,
            capacity=self.burst,
            refill_rate=self.requests_per_second,
            cost=cost,
            now=now,
        )


# Global singleton rate limiter instance
rate_limiter = RateLimiter()
