import asyncio
import json
import logging
import time
from typing import AsyncIterator, List, Optional, Tuple

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.base import (
    LLMProvider,
    ProviderException,
    ProviderTimeoutError,
)
from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.failure_classifier import FailureCategory, classify_failure
from gateway.src.reliability.health import ProviderHealthTracker
from gateway.src.reliability.metrics import ReliabilityMetrics
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

logger = logging.getLogger("tollgate.reliability.executor")


class ExecutionMetadata:
    def __init__(self, primary_provider: str):
        self.total_attempts: int = 0
        self.primary_provider: str = primary_provider
        self.final_provider: Optional[str] = None
        self.fallback_used: bool = False
        self.providers_attempted: List[str] = []
        self.failures: List[dict] = []
        self.latency_ms: float = 0.0

    def record_attempt(self, provider_name: str):
        self.total_attempts += 1
        if provider_name not in self.providers_attempted:
            self.providers_attempted.append(provider_name)
        self.final_provider = provider_name
        if provider_name != self.primary_provider:
            self.fallback_used = True

    def record_failure(
        self,
        provider_name: str,
        attempt: int,
        category: FailureCategory,
        error_msg: str,
        latency_ms: float,
    ):
        self.failures.append(
            {
                "provider": provider_name,
                "attempt": attempt,
                "category": category.value,
                "message": error_msg,
                "latency_ms": latency_ms,
            }
        )

    def to_dict(self) -> dict:
        return {
            "total_attempts": self.total_attempts,
            "primary_provider": self.primary_provider,
            "final_provider": self.final_provider,
            "fallback_used": self.fallback_used,
            "providers_attempted": self.providers_attempted,
            "failures_count": len(self.failures),
        }


class ReliableExecutor:
    """
    Executes LLM requests with bounded retries, exponential backoff,
    jitter, deadlines, health tracking, and deterministic fallback.
    """

    def __init__(
        self,
        health: Optional[ProviderHealthTracker] = None,
        metric_recorder: Optional[ReliabilityMetrics] = None,
        backoff_strategy: Optional[BackoffStrategy] = None,
    ):
        self.health = health if health is not None else ProviderHealthTracker()
        self.metrics = metric_recorder if metric_recorder is not None else ReliabilityMetrics()
        self._backoff = backoff_strategy

    def _get_backoff(self, policy: ReliabilityPolicy) -> BackoffStrategy:
        if self._backoff is not None:
            return self._backoff
        return BackoffStrategy(
            base_delay=policy.base_delay,
            max_delay=policy.max_delay,
            jitter=policy.jitter,
        )

    async def execute_chat(
        self,
        request: ChatCompletionRequest,
        route: FallbackRoute,
        providers_map: dict[str, LLMProvider],
        ctx: AuthenticatedContext,
        request_id: str,
        policy: Optional[ReliabilityPolicy] = None,
    ) -> Tuple[ChatCompletionResponse, ExecutionMetadata]:
        active_policy = policy or ReliabilityPolicy.from_settings()
        backoff = self._get_backoff(active_policy)
        metadata = ExecutionMetadata(primary_provider=route.primary.provider_name)

        start_time = time.time()
        deadline = start_time + active_policy.overall_timeout_seconds

        all_targets: List[ProviderTarget] = [route.primary] + route.fallbacks
        last_error: Optional[Exception] = None

        for target_idx, target in enumerate(all_targets):
            provider = providers_map.get(target.provider_name)
            if not provider:
                logger.warning(f"Target provider '{target.provider_name}' not registered, skipping")
                continue

            # Check health state
            if not self.health.is_available(provider.name) and target_idx < len(all_targets) - 1:
                logger.info(
                    f"Provider '{provider.name}' currently unhealthy/cooldown, skipping to next fallback"
                )
                continue

            if target_idx > 0:
                self.metrics.inc_fallbacks(provider.name)
                logger.info(
                    f"Initiating fallback to '{provider.name}' (model: {target.upstream_model}) for request {request_id}"
                )

            # Attempt loop for this provider
            for attempt in range(1, active_policy.max_attempts + 1):
                now = time.time()
                remaining_deadline = deadline - now
                if remaining_deadline <= 0:
                    last_error = ProviderTimeoutError(
                        f"Overall request timeout of {active_policy.overall_timeout_seconds}s exceeded"
                    )
                    break

                metadata.record_attempt(provider.name)
                self.metrics.inc_requests(provider.name)

                attempt_start = time.perf_counter()
                timeout_for_call = min(active_policy.provider_timeout_seconds, remaining_deadline)

                try:
                    res = await asyncio.wait_for(
                        provider.chat(request, target.upstream_model, request_id),
                        timeout=timeout_for_call,
                    )
                    latency_ms = (time.perf_counter() - attempt_start) * 1000.0
                    self.metrics.record_latency(provider.name, latency_ms)
                    self.health.record_success(provider.name)
                    return res, metadata

                except asyncio.TimeoutError:
                    err = ProviderTimeoutError(
                        f"Provider {provider.name} call timed out after {timeout_for_call}s"
                    )
                    self.metrics.inc_timeouts(provider.name)
                    classified = classify_failure(err)
                except Exception as e:
                    err = e
                    classified = classify_failure(err)

                latency_ms = (time.perf_counter() - attempt_start) * 1000.0
                self.metrics.inc_failures(provider.name)
                self.health.record_failure(provider.name, reason=classified.message)
                metadata.record_failure(
                    provider_name=provider.name,
                    attempt=attempt,
                    category=classified.category,
                    error_msg=classified.message,
                    latency_ms=latency_ms,
                )
                last_error = err

                # Non-retryable error -> do not retry with this provider
                if not classified.is_retryable:
                    logger.warning(
                        f"Non-retryable failure on {provider.name}: {classified.category.value} ({classified.message})"
                    )
                    break

                # If attempts exhausted for this provider
                if attempt >= active_policy.max_attempts:
                    logger.warning(
                        f"Exhausted {active_policy.max_attempts} attempts on {provider.name}"
                    )
                    break

                # Calculate backoff delay
                delay = backoff.compute_delay(attempt, classified.retry_after)
                if time.time() + delay >= deadline:
                    logger.warning(f"Insufficient remaining deadline to retry on {provider.name}")
                    break

                self.metrics.inc_retries(provider.name)
                logger.info(
                    f"Retrying {provider.name} in {delay}s (attempt {attempt + 1}/{active_policy.max_attempts})"
                )
                await backoff.sleep(delay)

            # Check if we should fallback after exhausting this target
            if last_error:
                classified = classify_failure(last_error)
                if not classified.is_fallback_eligible:
                    # Client errors (400, not found) should fail immediately without fallback
                    raise last_error

        # If all providers and retries were exhausted
        if last_error:
            raise last_error

        raise ProviderException("No available provider could fulfill the request", status_code=503)

    async def execute_stream(
        self,
        request: ChatCompletionRequest,
        route: FallbackRoute,
        providers_map: dict[str, LLMProvider],
        ctx: AuthenticatedContext,
        request_id: str,
        policy: Optional[ReliabilityPolicy] = None,
    ) -> AsyncIterator[str]:
        active_policy = policy or ReliabilityPolicy.from_settings()
        backoff = self._get_backoff(active_policy)
        metadata = ExecutionMetadata(primary_provider=route.primary.provider_name)

        start_time = time.time()
        deadline = start_time + active_policy.overall_timeout_seconds
        all_targets: List[ProviderTarget] = [route.primary] + route.fallbacks

        for target_idx, target in enumerate(all_targets):
            provider = providers_map.get(target.provider_name)
            if not provider:
                continue

            if not self.health.is_available(provider.name) and target_idx < len(all_targets) - 1:
                continue

            if target_idx > 0:
                self.metrics.inc_fallbacks(provider.name)

            for attempt in range(1, active_policy.max_attempts + 1):
                now = time.time()
                remaining_deadline = deadline - now
                if remaining_deadline <= 0:
                    yield f"data: {json.dumps({'error': {'message': 'Overall request deadline exceeded', 'type': 'timeout_error', 'code': 'timeout'}})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                metadata.record_attempt(provider.name)
                self.metrics.inc_requests(provider.name)

                chunks_emitted = 0
                attempt_failed = False
                error_to_raise: Optional[Exception] = None

                try:
                    stream_iter = provider.stream(request, target.upstream_model, request_id)
                    async for chunk in stream_iter:
                        chunks_emitted += 1
                        chunk_json = chunk.model_dump_json(exclude_none=True)
                        yield f"data: {chunk_json}\n\n"

                    # Successfully finished stream!
                    yield "data: [DONE]\n\n"
                    self.health.record_success(provider.name)
                    return

                except asyncio.CancelledError:
                    logger.info(f"Stream cancelled by client for request {request_id}")
                    raise
                except Exception as e:
                    attempt_failed = True
                    error_to_raise = e

                if attempt_failed and error_to_raise:
                    classified = classify_failure(error_to_raise)
                    self.metrics.inc_failures(provider.name)
                    self.health.record_failure(provider.name, reason=classified.message)

                    # CASE B: Partial stream was ALREADY sent to client!
                    # CRITICAL RULE: DO NOT transparently restart request!
                    if chunks_emitted > 0:
                        logger.warning(
                            f"Provider {provider.name} failed AFTER {chunks_emitted} chunks were emitted. "
                            f"Terminating stream safely without restart."
                        )
                        err_payload = {
                            "error": {
                                "message": "Stream interrupted by upstream failure",
                                "type": classified.category.value,
                                "code": "stream_interrupted",
                            }
                        }
                        yield f"data: {json.dumps(err_payload)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    # CASE A: Failure happened BEFORE any chunks were sent!
                    if not classified.is_retryable:
                        break

                    if attempt >= active_policy.max_attempts:
                        break

                    delay = backoff.compute_delay(attempt, classified.retry_after)
                    if time.time() + delay >= deadline:
                        break

                    self.metrics.inc_retries(provider.name)
                    await backoff.sleep(delay)

            # Move to fallback target only if no chunks were emitted yet!
            if chunks_emitted > 0:
                return

        # If all providers failed before emitting any chunks
        err_payload = {
            "error": {
                "message": "All upstream model providers failed to respond.",
                "type": "upstream_error",
                "code": "provider_unavailable",
            }
        }
        yield f"data: {json.dumps(err_payload)}\n\n"
        yield "data: [DONE]\n\n"
