import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis
from gateway.src.config import settings
from gateway.src.redis import get_redis_client
from tollgate_core.usage import UsageEventPayload
from tollgate_core.usage_metrics import usage_metrics

logger = logging.getLogger("tollgate.usage.publisher")


class UsagePublisher:
    """
    Asynchronous publisher for emitting usage events to Redis Stream.
    Uses bounded retries and exponential backoff on transient errors.
    """

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis_client = redis_client

    async def _get_client(self) -> aioredis.Redis:
        if self._redis_client is not None:
            return self._redis_client
        return await get_redis_client()

    async def publish(self, event: UsageEventPayload) -> Optional[str]:
        """
        Publishes a normalized usage event to the configured Redis Stream.
        Returns the Redis message ID on success, or None on failure after retries.
        """
        client = await self._get_client()
        stream_name = settings.usage_stream
        entry = event.to_stream_entry()

        attempts = max(1, settings.usage_max_retries)
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                message_id = await client.xadd(stream_name, entry)
                usage_metrics.increment("usage_events_published_total")
                logger.info(
                    f"Usage event published: request_id={event.request_id} event_id={event.event_id} "
                    f"stream={stream_name} message_id={message_id}"
                )
                return message_id
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Usage event publish attempt {attempt}/{attempts} failed: "
                    f"request_id={event.request_id} event_id={event.event_id} error={e}"
                )
                if attempt < attempts:
                    delay = min(
                        settings.usage_retry_base_delay * (2 ** (attempt - 1)),
                        settings.usage_retry_max_delay,
                    )
                    await asyncio.sleep(delay)

        usage_metrics.increment("usage_event_publish_failures_total")
        logger.error(
            f"Failed to publish usage event after {attempts} attempts: "
            f"request_id={event.request_id} event_id={event.event_id} error={last_error}"
        )
        return None


usage_publisher = UsagePublisher()
