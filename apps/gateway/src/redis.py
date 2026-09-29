from typing import Optional
import redis.asyncio as aioredis
from gateway.src.config import settings

redis_client: Optional[aioredis.Redis] = None


async def get_redis_client() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
    return redis_client


async def check_redis_health() -> bool:
    try:
        client = await get_redis_client()
        return await client.ping()
    except Exception:
        return False


async def close_redis_connection() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
