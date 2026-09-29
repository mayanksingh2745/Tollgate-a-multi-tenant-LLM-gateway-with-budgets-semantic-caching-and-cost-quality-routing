import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add core src to path
root_dir = Path(__file__).resolve().parents[3]
core_src = root_dir / "packages" / "core" / "src"
if str(core_src) not in sys.path:
    sys.path.insert(0, str(core_src))

import redis.asyncio as aioredis
from tollgate_core.config import settings

logging.basicConfig(
    level=settings.log_level, format="%(asctime)s [%(levelname)s] [Worker] %(message)s"
)
logger = logging.getLogger("tollgate.worker")


async def heartbeat_loop(redis_client: aioredis.Redis):
    logger.info("Worker heartbeat loop starting...")
    while True:
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            await redis_client.set("tollgate:worker:heartbeat", timestamp, ex=60)
            logger.info(f"Worker heartbeat recorded at {timestamp}")
        except Exception as e:
            logger.error(f"Worker heartbeat failed: {e}")
        await asyncio.sleep(15)


async def main():
    logger.info(f"Initializing Tollgate Worker Service [{settings.environment}]...")
    redis_client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

    # Test Redis connection
    try:
        ping = await redis_client.ping()
        if ping:
            logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")

    # Start background task loop
    try:
        await heartbeat_loop(redis_client)
    except asyncio.CancelledError:
        logger.info("Worker received shutdown signal.")
    finally:
        await redis_client.aclose()
        logger.info("Worker cleanly shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker terminated by keyboard interrupt.")
