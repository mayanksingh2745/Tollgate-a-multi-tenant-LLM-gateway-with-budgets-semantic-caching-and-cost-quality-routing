import asyncio
import logging
import time
import uuid
from typing import Any, Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tollgate_core.config import settings
from tollgate_core.observability import (
    current_project_id,
    current_request_id,
    current_tenant_id,
    extract_trace_context,
    get_tracer,
    safe_set_attribute,
)
from tollgate_core.usage import DeadLetterPayload, UsageEventPayload
from tollgate_core.usage_metrics import usage_metrics

from apps.worker.src.persistence import persist_usage_event

logger = logging.getLogger("tollgate.worker.consumer")
tracer = get_tracer("tollgate.worker")


class UsageWorkerConsumer:
    """
    Durable Redis Stream consumer group worker.
    Reads usage events from Redis Stream, validates payloads, persists to PostgreSQL with
    daily/monthly rollups in an atomic transaction, only ACK-ing on successful commit.
    Reclaims stale pending messages from crashed workers and quarantines malformed events.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        session_factory: async_sessionmaker[AsyncSession],
        consumer_group: Optional[str] = None,
        consumer_name: Optional[str] = None,
        stream_name: Optional[str] = None,
        dead_letter_stream: Optional[str] = None,
        batch_size: Optional[int] = None,
        claim_idle_seconds: Optional[int] = None,
        block_ms: Optional[int] = None,
    ):
        self.redis_client = redis_client
        self.session_factory = session_factory
        self.consumer_group = consumer_group or settings.usage_consumer_group
        self.consumer_name = (
            consumer_name or settings.usage_consumer_name or f"usage-worker-{uuid.uuid4().hex[:8]}"
        )
        self.stream_name = stream_name or settings.usage_stream
        self.dead_letter_stream = dead_letter_stream or settings.usage_dead_letter_stream
        self.batch_size = batch_size or settings.usage_batch_size
        self.claim_idle_seconds = claim_idle_seconds or settings.usage_claim_idle_seconds
        self.block_ms = block_ms or settings.usage_block_ms

        self.running: bool = False
        self.last_claim_time: float = 0.0

    async def ensure_consumer_group(self) -> None:
        """
        Safely creates the consumer group and stream if they do not exist.
        Handles BUSYGROUP error without failing.
        """
        try:
            await self.redis_client.xgroup_create(
                self.stream_name, self.consumer_group, id="0", mkstream=True
            )
            logger.info(
                f"Consumer group '{self.consumer_group}' created on stream '{self.stream_name}'."
            )
        except Exception as e:
            if "BUSYGROUP" in str(e):
                logger.info(
                    f"Consumer group '{self.consumer_group}' already exists on stream '{self.stream_name}'."
                )
            else:
                logger.error(f"Failed to create consumer group '{self.consumer_group}': {e}")
                raise

    async def quarantine_message(
        self,
        message_id: str,
        raw_data: Any,
        reason: str,
        failure_type: str,
    ) -> None:
        """
        Moves unprocessable or malformed message to dead-letter stream, then ACKs it
        from the main stream so it does not block worker processing forever.
        """
        event_id = None
        if isinstance(raw_data, dict):
            event_id = raw_data.get("event_id")

        sanitized_payload = str(raw_data)[:2000]
        dead_letter = DeadLetterPayload(
            original_event_id=str(event_id) if event_id else None,
            failure_reason=reason,
            failure_type=failure_type,
            original_payload=sanitized_payload,
        )
        try:
            await self.redis_client.xadd(self.dead_letter_stream, dead_letter.to_stream_entry())
            await self.redis_client.xack(self.stream_name, self.consumer_group, message_id)
            usage_metrics.increment("usage_dead_letter_events_total")
            logger.warning(
                f"Quarantined message {message_id} to dead-letter stream '{self.dead_letter_stream}': {reason}"
            )
        except Exception as dl_err:
            logger.error(
                f"Failed to quarantine message {message_id} to dead-letter stream: {dl_err}"
            )

    async def process_message(self, message_id: str, message_data: dict) -> bool:
        """
        Processes a single message: validates payload, persists to DB, and ACKs on commit.
        Returns True if processed (or quarantined/ACKed), False if transient failure occurred.
        """
        t0 = time.perf_counter()

        # 1. Validation
        try:
            event = UsageEventPayload.from_stream_entry(message_data)
        except Exception as val_err:
            logger.warning(f"Event schema validation failed for message {message_id}: {val_err}")
            await self.quarantine_message(
                message_id=message_id,
                raw_data=message_data,
                reason=str(val_err),
                failure_type="validation_error",
            )
            return True

        # 2. Extract Trace Context and Process in Span
        extracted_ctx = (
            extract_trace_context({"traceparent": event.traceparent}) if event.traceparent else None
        )

        with tracer.start_as_current_span("usage.process", context=extracted_ctx) as proc_span:
            safe_set_attribute(proc_span, "tollgate.request_id", event.request_id)
            safe_set_attribute(proc_span, "tollgate.event_id", str(event.event_id))
            safe_set_attribute(proc_span, "tollgate.tenant_id", str(event.tenant_id))
            safe_set_attribute(proc_span, "tollgate.project_id", str(event.project_id))
            safe_set_attribute(proc_span, "tollgate.provider", event.provider)
            safe_set_attribute(proc_span, "tollgate.model", event.model)

            current_request_id.set(event.request_id)
            current_tenant_id.set(str(event.tenant_id))
            current_project_id.set(str(event.project_id))

            # Database Persistence in Atomic Transaction
            try:
                async with self.session_factory() as session:
                    if session.in_transaction():
                        await persist_usage_event(session, event)
                        await session.commit()
                    else:
                        async with session.begin():
                            await persist_usage_event(session, event)

                # 3. Message Acknowledgement AFTER successful DB commit
                await self.redis_client.xack(self.stream_name, self.consumer_group, message_id)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                safe_set_attribute(proc_span, "duration_ms", latency_ms)
                safe_set_attribute(proc_span, "status", "success")
                usage_metrics.record_latency(latency_ms)
                usage_metrics.increment("usage_worker_events_processed_total")
                logger.debug(
                    f"Usage event processed and ACKed: message_id={message_id} "
                    f"event_id={event.event_id} request_id={event.request_id} latency_ms={latency_ms:.2f}"
                )
                return True
            except Exception as db_err:
                safe_set_attribute(proc_span, "status", "failure")
                safe_set_attribute(proc_span, "failure_category", "database_error")
                logger.error(
                    f"Database persistence failed for message {message_id} "
                    f"(event_id={event.event_id} request_id={event.request_id}): {db_err}"
                )
                usage_metrics.increment("usage_worker_events_failed_total")
                # CRITICAL: Do NOT ACK message on DB failure; message remains pending for retry/reclaim
                return False

    async def reclaim_stale_messages(self) -> int:
        """
        Reclaims and processes messages that have been pending longer than claim_idle_seconds.
        Supports modern XAUTOCLAIM with fallback to XPENDING / XCLAIM.
        """
        min_idle_ms = int(self.claim_idle_seconds * 1000)
        reclaimed_count = 0

        # Try XAUTOCLAIM first
        try:
            claim_res = await self.redis_client.xautoclaim(
                self.stream_name,
                self.consumer_group,
                self.consumer_name,
                min_idle_time=min_idle_ms,
                start_id="0-0",
                count=self.batch_size,
            )
            # Response: (next_id, [(msg_id, msg_data), ...], [deleted_ids...])
            if claim_res and len(claim_res) > 1:
                messages = claim_res[1]
                for msg_id, msg_data in messages:
                    usage_metrics.increment("usage_worker_events_reclaimed_total")
                    ok = await self.process_message(msg_id, msg_data)
                    if ok:
                        reclaimed_count += 1
                if messages:
                    logger.info(
                        f"Consumer '{self.consumer_name}' reclaimed and processed {len(messages)} stale message(s)."
                    )
            return reclaimed_count
        except Exception as autoclaim_err:
            logger.debug(
                f"xautoclaim encountered or unsupported ({autoclaim_err}); attempting fallback."
            )

        # Fallback to XPENDING_RANGE + XCLAIM
        try:
            pending = await self.redis_client.xpending_range(
                self.stream_name,
                self.consumer_group,
                min="-",
                max="+",
                count=self.batch_size,
            )
            for p in pending:
                idle = p.get("idle", 0) if isinstance(p, dict) else getattr(p, "idle", 0)
                msg_id = (
                    p.get("message_id") if isinstance(p, dict) else getattr(p, "message_id", None)
                )
                if msg_id and idle >= min_idle_ms:
                    claimed = await self.redis_client.xclaim(
                        self.stream_name,
                        self.consumer_group,
                        self.consumer_name,
                        min_idle_time=min_idle_ms,
                        message_ids=[msg_id],
                    )
                    for c_id, c_data in claimed:
                        usage_metrics.increment("usage_worker_events_reclaimed_total")
                        ok = await self.process_message(c_id, c_data)
                        if ok:
                            reclaimed_count += 1
            return reclaimed_count
        except Exception as fallback_err:
            logger.warning(f"Fallback pending check failed: {fallback_err}")
            return reclaimed_count

    async def consume_batch(self) -> int:
        """
        Consumes one batch of new messages, reclaiming pending messages if overdue.
        Returns the number of successfully processed messages in this batch.
        """
        now = time.time()
        # Periodically reclaim stale messages
        if now - self.last_claim_time > max(5.0, self.claim_idle_seconds / 2):
            await self.reclaim_stale_messages()
            self.last_claim_time = now

        try:
            resp = await self.redis_client.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                {self.stream_name: ">"},
                count=self.batch_size,
                block=self.block_ms,
            )
        except Exception as read_err:
            logger.error(f"Error reading from Redis Stream '{self.stream_name}': {read_err}")
            raise

        if not resp:
            return 0

        processed = 0
        for _stream, messages in resp:
            usage_metrics.record_batch_size(len(messages))
            for msg_id, msg_data in messages:
                ok = await self.process_message(msg_id, msg_data)
                if ok:
                    processed += 1

        return processed

    async def run(self) -> None:
        """
        Main worker consumption loop. Runs until stop() is called.
        """
        self.running = True
        logger.info(
            f"Starting UsageWorkerConsumer '{self.consumer_name}' on group '{self.consumer_group}' "
            f"stream '{self.stream_name}' [batch_size={self.batch_size}, claim_idle={self.claim_idle_seconds}s]..."
        )
        await self.ensure_consumer_group()

        backoff = settings.usage_retry_base_delay
        while self.running:
            try:
                await self.consume_batch()
                backoff = settings.usage_retry_base_delay  # Reset backoff on success
            except asyncio.CancelledError:
                logger.info(f"Consumer '{self.consumer_name}' received cancellation request.")
                break
            except Exception as e:
                logger.warning(f"Consumer loop error: {e}. Backing off for {backoff:.2f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, settings.usage_retry_max_delay)

        logger.info(f"Consumer '{self.consumer_name}' stopped cleanly.")

    def stop(self) -> None:
        self.running = False
