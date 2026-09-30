import asyncio
import time
from typing import Optional, Union

import redis.asyncio as aioredis
from gateway.src.config import settings
from tollgate_core.observability import record_redis_operation

_raw_redis_client: Optional[aioredis.Redis] = None


class InstrumentedRedis:
    """
    Transparent proxy wrapping aioredis.Redis to record bounded Prometheus
    operation latencies, success rates, and errors.
    """

    def __init__(self, client: aioredis.Redis, component: str = "gateway"):
        self._client = client
        self._component = component

    def __getattr__(self, name: str):
        attr = getattr(self._client, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                res = attr(*args, **kwargs)
                if asyncio.iscoroutine(res):
                    async def async_call():
                        t0 = time.perf_counter()
                        try:
                            val = await res
                            record_redis_operation(
                                operation=name.lower()[:32],
                                component=self._component,
                                duration_seconds=time.perf_counter() - t0,
                                success=True,
                            )
                            return val
                        except Exception:
                            record_redis_operation(
                                operation=name.lower()[:32],
                                component=self._component,
                                duration_seconds=time.perf_counter() - t0,
                                success=False,
                            )
                            raise
                    return async_call()
                return res
            return wrapper
        return attr


async def get_raw_redis_client() -> aioredis.Redis:
    global _raw_redis_client
    if _raw_redis_client is None:
        _raw_redis_client = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _raw_redis_client


async def get_redis_client(component: str = "gateway") -> Union[InstrumentedRedis, aioredis.Redis]:
    client = await get_raw_redis_client()
    return InstrumentedRedis(client, component=component)


async def check_redis_health() -> bool:
    try:
        client = await get_redis_client(component="health")
        return bool(await client.ping())
    except Exception:
        return False


async def close_redis_connection() -> None:
    global _raw_redis_client
    if _raw_redis_client is not None:
        await _raw_redis_client.aclose()
        _raw_redis_client = None
