import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add core and apps to path
root_dir = Path(__file__).resolve().parents[3]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from tollgate_core.config import settings

from apps.worker.src.consumer import UsageWorkerConsumer

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] [UsageWorker] %(message)s",
)
logger = logging.getLogger("tollgate.worker")


async def heartbeat_loop(
    redis_client: aioredis.Redis,
    engine,
    consumer_name: str,
    stop_event: asyncio.Event,
):
    logger.info("Worker health & heartbeat monitor starting...")
    while not stop_event.is_set():
        try:
            redis_ok = await redis_client.ping()
        except Exception:
            redis_ok = False

        db_ok = False
        try:
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT 1"))
                db_ok = res.scalar() == 1
        except Exception:
            db_ok = False

        status_str = "healthy" if (redis_ok and db_ok) else "degraded"
        payload = {
            "status": status_str,
            "redis_connected": bool(redis_ok),
            "db_connected": bool(db_ok),
            "consumer_name": consumer_name,
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await redis_client.set("tollgate:worker:heartbeat", json.dumps(payload), ex=60)
            logger.debug(f"Worker heartbeat recorded: {status_str}")
        except Exception as e:
            logger.warning(f"Failed to record worker heartbeat: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass


async def main():
    logger.info(f"Initializing Tollgate Usage Worker [{settings.environment}]...")

    redis_client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    consumer = UsageWorkerConsumer(
        redis_client=redis_client,
        session_factory=session_factory,
    )

    stop_event = asyncio.Event()

    def handle_shutdown_signal():
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        consumer.stop()
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_shutdown_signal)
        except NotImplementedError:
            # Windows may not support add_signal_handler for some signals
            pass

    consumer_task = asyncio.create_task(consumer.run())
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(redis_client, engine, consumer.consumer_name, stop_event)
    )

    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        logger.info("Closing database engine and Redis connection...")
        await engine.dispose()
        await redis_client.aclose()
        logger.info("Tollgate Usage Worker shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker terminated by user interrupt.")
