import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from uuid import UUID

import redis.asyncio as aioredis
from gateway.src.cache.canonicalizer import Canonicalizer
from gateway.src.cache.metrics import cache_metrics
from gateway.src.config import settings
from gateway.src.redis import get_redis_client
from gateway.src.schemas.chat import ChatCompletionRequest, ChatCompletionResponse

logger = logging.getLogger("tollgate.cache.service")

CACHE_SCHEMA_VERSION = 1


class BaseCacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        pass

    @abstractmethod
    async def get_version(self, version_key: str) -> int:
        pass

    @abstractmethod
    async def increment_version(self, version_key: str) -> int:
        pass

    @abstractmethod
    async def increment_counter(self, key: str, amount: int = 1) -> int:
        pass

    @abstractmethod
    async def get_counter(self, key: str) -> int:
        pass


class RedisCacheBackend(BaseCacheBackend):
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis_client = redis_client

    async def _get_client(self) -> aioredis.Redis:
        if self._redis_client is not None:
            return self._redis_client
        return await get_redis_client()

    async def get(self, key: str) -> Optional[str]:
        client = await self._get_client()
        return await client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        client = await self._get_client()
        await client.set(key, value, ex=ttl_seconds)
        return True

    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        res = await client.delete(key)
        return bool(res > 0)

    async def get_version(self, version_key: str) -> int:
        client = await self._get_client()
        val = await client.get(version_key)
        return int(val) if val is not None else 1

    async def increment_version(self, version_key: str) -> int:
        client = await self._get_client()
        return await client.incr(version_key)

    async def increment_counter(self, key: str, amount: int = 1) -> int:
        client = await self._get_client()
        return await client.incrby(key, amount)

    async def get_counter(self, key: str) -> int:
        client = await self._get_client()
        val = await client.get(key)
        return int(val) if val is not None else 0


class InMemoryCacheBackend(BaseCacheBackend):
    def __init__(self):
        self._store: Dict[str, Tuple[str, float]] = {}
        self._versions: Dict[str, int] = {}
        self._counters: Dict[str, int] = {}

    async def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if not entry:
            return None
        val, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return val

    async def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        self._store[key] = (value, time.time() + ttl_seconds)
        return True

    async def delete(self, key: str) -> bool:
        return bool(self._store.pop(key, None))

    async def get_version(self, version_key: str) -> int:
        return self._versions.get(version_key, 1)

    async def increment_version(self, version_key: str) -> int:
        new_v = self._versions.get(version_key, 1) + 1
        self._versions[version_key] = new_v
        return new_v

    async def increment_counter(self, key: str, amount: int = 1) -> int:
        self._counters[key] = self._counters.get(key, 0) + amount
        return self._counters[key]

    async def get_counter(self, key: str) -> int:
        return self._counters.get(key, 0)

    def clear(self) -> None:
        self._store.clear()
        self._versions.clear()
        self._counters.clear()


class ExactResponseCache:
    """
    Tenant-safe, exact-match response cache for OpenAI-compatible chat completions.
    Provides fail-open resilience, O(1) project cache invalidation via generation counters,
    and automatic TTL expiration.
    """

    def __init__(self, backend: Optional[BaseCacheBackend] = None):
        self.backend = backend or RedisCacheBackend()

    async def _build_cache_key(
        self,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> str:
        version_key = f"{settings.cache_redis_prefix}:ver:{tenant_id}:{project_id}"
        try:
            version = await self.backend.get_version(version_key)
        except Exception as e:
            logger.warning(f"Failed to read project cache version: {e}; falling back to 1")
            version = 1

        request_hash = Canonicalizer.compute_hash(
            request=request,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
        )
        return (
            f"{settings.cache_redis_prefix}:res:{tenant_id}:{project_id}:{version}:{request_hash}"
        )

    async def build_cache_key(
        self,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> str:
        return await self._build_cache_key(
            request=request,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
        )

    async def get(
        self,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> Optional[ChatCompletionResponse]:
        """
        Looks up cached response. Returns ChatCompletionResponse on HIT, or None on MISS/BYPASS/Error.
        Fails open if Redis lookup encounters an error.
        """
        is_cacheable, bypass_reason = Canonicalizer.is_cacheable(request)
        if not is_cacheable:
            cache_metrics.increment("cache_bypasses_total")
            logger.debug(f"Cache lookup bypassed: reason={bypass_reason}")
            return None

        t0 = time.perf_counter()
        try:
            cache_key = await self._build_cache_key(
                request=request,
                tenant_id=tenant_id,
                project_id=project_id,
                provider=provider,
            )
            raw_entry = await self.backend.get(cache_key)
        except Exception as e:
            # Section 24: Fail-open on cache lookup failure
            cache_metrics.increment("cache_lookup_errors_total")
            logger.warning(f"Cache lookup failed unexpectedly (failing open): {e}")
            return None

        latency_ms = (time.perf_counter() - t0) * 1000.0
        cache_metrics.record_lookup_latency(latency_ms)

        if raw_entry is None:
            cache_metrics.increment("cache_misses_total")
            await self.record_tenant_miss(tenant_id, project_id)
            logger.debug(f"Cache MISS for model={request.model} tenant={tenant_id}")
            return None

        try:
            entry = json.loads(raw_entry)
            # Validate cache schema version (Section 20)
            if entry.get("cache_version") != CACHE_SCHEMA_VERSION:
                logger.warning(
                    f"Unsupported cache schema version {entry.get('cache_version')}; invalidating entry"
                )
                await self.backend.delete(cache_key)
                cache_metrics.increment("cache_misses_total")
                await self.record_tenant_miss(tenant_id, project_id)
                return None

            response_data = entry.get("response")
            cached_response = ChatCompletionResponse.model_validate(response_data)
            cache_metrics.increment("cache_hits_total")
            await self.record_tenant_hit(tenant_id, project_id)
            logger.info(
                f"Cache HIT: model={request.model} provider={provider} "
                f"tenant_id={tenant_id} latency_ms={latency_ms:.2f}"
            )
            return cached_response
        except Exception as parse_err:
            logger.warning(f"Failed to deserialize cached response (treating as miss): {parse_err}")
            await self.backend.delete(cache_key)
            cache_metrics.increment("cache_misses_total")
            await self.record_tenant_miss(tenant_id, project_id)
            return None

    async def record_tenant_hit(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> None:
        try:
            t_key = f"{settings.cache_redis_prefix}:stats:hits:{tenant_id}"
            await self.backend.increment_counter(t_key)
            if project_id:
                p_key = f"{settings.cache_redis_prefix}:stats:hits:{tenant_id}:{project_id}"
                await self.backend.increment_counter(p_key)
        except Exception:
            pass

    async def record_tenant_miss(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> None:
        try:
            t_key = f"{settings.cache_redis_prefix}:stats:misses:{tenant_id}"
            await self.backend.increment_counter(t_key)
            if project_id:
                p_key = f"{settings.cache_redis_prefix}:stats:misses:{tenant_id}:{project_id}"
                await self.backend.increment_counter(p_key)
        except Exception:
            pass

    async def get_tenant_hits(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> int:
        try:
            key = (
                f"{settings.cache_redis_prefix}:stats:hits:{tenant_id}:{project_id}"
                if project_id
                else f"{settings.cache_redis_prefix}:stats:hits:{tenant_id}"
            )
            return await self.backend.get_counter(key)
        except Exception:
            return 0

    async def get_tenant_misses(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> int:
        try:
            key = (
                f"{settings.cache_redis_prefix}:stats:misses:{tenant_id}:{project_id}"
                if project_id
                else f"{settings.cache_redis_prefix}:stats:misses:{tenant_id}"
            )
            return await self.backend.get_counter(key)
        except Exception:
            return 0

    async def set(
        self,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> bool:
        """
        Stores successful provider response in exact cache with configured TTL.
        Fails open if storage fails or response exceeds maximum size.
        """
        is_cacheable, _ = Canonicalizer.is_cacheable(request)
        if not is_cacheable:
            return False

        t0 = time.perf_counter()
        try:
            cache_key = await self._build_cache_key(
                request=request,
                tenant_id=tenant_id,
                project_id=project_id,
                provider=provider,
            )

            envelope = {
                "cache_version": CACHE_SCHEMA_VERSION,
                "tenant_id": str(tenant_id),
                "project_id": str(project_id),
                "provider": provider,
                "model": request.model,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "response": response.model_dump(exclude_none=True),
            }
            serialized = json.dumps(envelope, separators=(",", ":"))

            # Section 22: Enforce maximum response byte limit
            if len(serialized.encode("utf-8")) > settings.cache_max_response_bytes:
                cache_metrics.increment("cache_response_too_large_total")
                logger.info(
                    f"Response size ({len(serialized)} bytes) exceeds cache limit; skipping cache write"
                )
                return False

            ttl = settings.cache_ttl_seconds
            await self.backend.set(cache_key, serialized, ttl_seconds=ttl)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            cache_metrics.record_write_latency(latency_ms)
            logger.debug(
                f"Cached response stored: key={cache_key} ttl={ttl}s latency_ms={latency_ms:.2f}"
            )
            return True
        except Exception as e:
            # Section 24: Fail-open on write failure
            cache_metrics.increment("cache_write_errors_total")
            logger.warning(f"Failed to write response to cache (ignoring): {e}")
            return False

    async def invalidate_project(self, tenant_id: UUID, project_id: UUID) -> int:
        """
        Atomically invalidates all cache entries for a project by incrementing
        its cache generation version counter in O(1) time.
        """
        version_key = f"{settings.cache_redis_prefix}:ver:{tenant_id}:{project_id}"
        new_version = await self.backend.increment_version(version_key)
        logger.info(
            f"Invalidated cache for tenant={tenant_id} project={project_id} (new_version={new_version})"
        )
        return new_version

    async def invalidate_key(
        self,
        request: ChatCompletionRequest,
        tenant_id: UUID,
        project_id: UUID,
        provider: str,
    ) -> bool:
        """
        Deletes a specific exact cache entry.
        """
        cache_key = await self._build_cache_key(
            request=request,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
        )
        return await self.backend.delete(cache_key)


exact_cache = ExactResponseCache()
