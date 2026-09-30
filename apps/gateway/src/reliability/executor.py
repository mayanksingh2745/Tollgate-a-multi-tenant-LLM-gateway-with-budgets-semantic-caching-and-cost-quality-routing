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
from gateway.src.reliability.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitState,
)
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
from tollgate_core.observability import (
    get_tracer,
    record_circuit_half_open_probe,
    record_circuit_rejection,
    record_circuit_transition,
    record_stream_duration,
    record_stream_failure,
    record_stream_request,
    record_stream_ttft,
    safe_set_attribute,
)

logger = logging.getLogger("tollgate.reliability.executor")
tracer = get_tracer("tollgate.executor")


class ExecutionMetadata:
    def __init__(self, primary_provider: str):
        self.total_attempts: int = 0
        self.primary_provider: str = primary_provider
        self.final_provider: Optional[str] = None
        self.fallback_used: bool = False
        self.providers_attempted: List[str] = []
        self.failures: List[dict] = []
        self.latency_ms: float = 0.0
        self.circuit_rejections: int = 0

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
            "circuit_rejections": self.circuit_rejections,
        }


class ReliableExecutor:
    """
    Executes LLM requests with bounded retries, exponential backoff,
    jitter, deadlines, health tracking, circuit breaking, and deterministic fallback.
    """

    def __init__(
        self,
        health: Optional[ProviderHealthTracker] = None,
        metric_recorder: Optional[ReliabilityMetrics] = None,
        backoff_strategy: Optional[BackoffStrategy] = None,
        circuit_breaker: Optional[CircuitBreakerRegistry] = None,
    ):
        self.health = health if health is not None else ProviderHealthTracker()
        self.metrics = metric_recorder if metric_recorder is not None else ReliabilityMetrics()
        self._backoff = backoff_strategy
        if circuit_breaker is not None:
            self.circuit_breaker = circuit_breaker
        else:
            from gateway.src.reliability.circuit_breaker import (
                create_circuit_breaker_registry_from_settings,
            )

            self.circuit_breaker = create_circuit_breaker_registry_from_settings()

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

        with tracer.start_as_current_span("provider.request") as req_span:
            safe_set_attribute(req_span, "tollgate.provider", route.primary.provider_name)
            safe_set_attribute(req_span, "tollgate.requested_model", request.model)
            safe_set_attribute(req_span, "tollgate.stream", False)

            for target_idx, target in enumerate(all_targets):
                provider = providers_map.get(target.provider_name)
                if not provider:
                    logger.warning(
                        f"Target provider '{target.provider_name}' not registered, skipping"
                    )
                    continue

                # Check health state (Phase 3 legacy health tracker)
                if (
                    not self.health.is_available(provider.name)
                    and target_idx < len(all_targets) - 1
                ):
                    logger.info(
                        f"Provider '{provider.name}' currently unhealthy/cooldown, skipping to next fallback"
                    )
                    continue

                # Circuit breaker check (Phase 12)
                circuit_decision = None
                if self.circuit_breaker:
                    circuit_decision = await self.circuit_breaker.before_call(
                        provider.name, target.upstream_model
                    )
                    if circuit_decision.is_open:
                        metadata.circuit_rejections += 1
                        record_circuit_rejection(provider.name, target.upstream_model)
                        with tracer.start_as_current_span("circuit.check") as cb_span:
                            safe_set_attribute(cb_span, "tollgate.circuit.state", circuit_decision.state.value)
                            safe_set_attribute(cb_span, "tollgate.circuit.action", "reject")
                            safe_set_attribute(cb_span, "tollgate.provider", provider.name)
                            safe_set_attribute(cb_span, "tollgate.model", target.upstream_model)
                        logger.info(
                            f"Circuit OPEN for {provider.name}:{target.upstream_model}, "
                            f"skipping to next fallback"
                        )
                        if target_idx < len(all_targets) - 1:
                            continue
                        # Last target — circuit still open, nothing to do
                        last_error = ProviderException(
                            f"All providers unavailable (circuit open for {provider.name})",
                            status_code=503,
                        )
                        break

                if target_idx > 0:
                    self.metrics.inc_fallbacks(
                        target_provider=provider.name,
                        source_provider=all_targets[target_idx - 1].provider_name,
                    )
                    logger.info(
                        f"Initiating fallback to '{provider.name}' (model: {target.upstream_model}) for request {request_id}"
                    )
                    with tracer.start_as_current_span("provider.fallback") as fb_span:
                        safe_set_attribute(fb_span, "tollgate.provider.fallback", True)
                        safe_set_attribute(
                            fb_span,
                            "tollgate.fallback.from_provider",
                            all_targets[target_idx - 1].provider_name,
                        )
                        safe_set_attribute(fb_span, "tollgate.fallback.to_provider", provider.name)
                        safe_set_attribute(
                            fb_span, "tollgate.fallback.model", target.upstream_model
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
                    self.metrics.inc_requests(provider.name, model=target.upstream_model)

                    attempt_start = time.perf_counter()
                    timeout_for_call = min(
                        active_policy.provider_timeout_seconds, remaining_deadline
                    )

                    with tracer.start_as_current_span("provider.attempt") as attempt_span:
                        safe_set_attribute(attempt_span, "tollgate.provider", provider.name)
                        safe_set_attribute(attempt_span, "tollgate.model", target.upstream_model)
                        safe_set_attribute(attempt_span, "tollgate.provider.attempt", attempt)
                        if circuit_decision and circuit_decision.is_probe:
                            safe_set_attribute(attempt_span, "tollgate.circuit.probe", True)

                        try:
                            res = await asyncio.wait_for(
                                provider.chat(request, target.upstream_model, request_id),
                                timeout=timeout_for_call,
                            )
                            latency_ms = (time.perf_counter() - attempt_start) * 1000.0
                            self.metrics.record_latency(
                                provider.name,
                                latency_ms,
                                model=target.upstream_model,
                                status_code=200,
                            )
                            self.health.record_success(provider.name)

                            # Circuit breaker: record success
                            if self.circuit_breaker:
                                await self.circuit_breaker.record_success(
                                    provider.name, target.upstream_model
                                )
                                if circuit_decision and circuit_decision.is_probe:
                                    record_circuit_half_open_probe(
                                        provider.name, target.upstream_model, "success"
                                    )

                            safe_set_attribute(attempt_span, "status", "success")
                            safe_set_attribute(attempt_span, "duration_ms", latency_ms)
                            safe_set_attribute(
                                req_span, "tollgate.actual_model", target.upstream_model
                            )
                            safe_set_attribute(req_span, "tollgate.provider", provider.name)
                            return res, metadata

                        except asyncio.TimeoutError:
                            err = ProviderTimeoutError(
                                f"Provider {provider.name} call timed out after {timeout_for_call}s"
                            )
                            self.metrics.inc_timeouts(provider.name, model=target.upstream_model)
                            classified = classify_failure(err)
                        except Exception as e:
                            err = e
                            classified = classify_failure(err)

                        latency_ms = (time.perf_counter() - attempt_start) * 1000.0
                        self.metrics.inc_failures(
                            provider.name,
                            model=target.upstream_model,
                            failure_category=classified.category.value,
                            latency_ms=latency_ms,
                        )
                        self.health.record_failure(provider.name, reason=classified.message)

                        # Circuit breaker: record failure
                        if self.circuit_breaker:
                            await self.circuit_breaker.record_failure(
                                provider.name, target.upstream_model, classified.category
                            )
                            if circuit_decision and circuit_decision.is_probe:
                                record_circuit_half_open_probe(
                                    provider.name, target.upstream_model, "failure"
                                )

                        metadata.record_failure(
                            provider_name=provider.name,
                            attempt=attempt,
                            category=classified.category,
                            error_msg=classified.message,
                            latency_ms=latency_ms,
                        )
                        safe_set_attribute(attempt_span, "status", "failure")
                        safe_set_attribute(
                            attempt_span, "failure_category", classified.category.value
                        )
                        safe_set_attribute(attempt_span, "duration_ms", latency_ms)
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
                        logger.warning(
                            f"Insufficient remaining deadline to retry on {provider.name}"
                        )
                        break

                    self.metrics.inc_retries(provider.name, model=target.upstream_model)
                    logger.info(
                        f"Retrying {provider.name} in {delay}s (attempt {attempt + 1}/{active_policy.max_attempts})"
                    )
                    with tracer.start_as_current_span("provider.retry") as retry_span:
                        safe_set_attribute(retry_span, "tollgate.provider", provider.name)
                        safe_set_attribute(retry_span, "tollgate.provider.retry", attempt)
                        safe_set_attribute(
                            retry_span, "failure_category", classified.category.value
                        )
                        safe_set_attribute(retry_span, "retry_delay_seconds", delay)

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

            raise ProviderException(
                "No available provider could fulfill the request", status_code=503
            )

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

        record_stream_request(provider=route.primary.provider_name, model=request.model)

        with tracer.start_as_current_span("provider.request") as req_span:
            safe_set_attribute(req_span, "tollgate.provider", route.primary.provider_name)
            safe_set_attribute(req_span, "tollgate.requested_model", request.model)
            safe_set_attribute(req_span, "tollgate.stream", True)

            for target_idx, target in enumerate(all_targets):
                provider = providers_map.get(target.provider_name)
                if not provider:
                    continue

                if (
                    not self.health.is_available(provider.name)
                    and target_idx < len(all_targets) - 1
                ):
                    continue

                # Circuit breaker check (Phase 12)
                circuit_decision = None
                if self.circuit_breaker:
                    circuit_decision = await self.circuit_breaker.before_call(
                        provider.name, target.upstream_model
                    )
                    if circuit_decision.is_open:
                        metadata.circuit_rejections += 1
                        record_circuit_rejection(provider.name, target.upstream_model)
                        logger.info(
                            f"Circuit OPEN for {provider.name}:{target.upstream_model} (stream), "
                            f"skipping to next fallback"
                        )
                        if target_idx < len(all_targets) - 1:
                            continue
                        # Last target — all circuits open
                        err_payload = {
                            "error": {
                                "message": "All upstream model providers unavailable.",
                                "type": "upstream_error",
                                "code": "circuit_open",
                            }
                        }
                        yield f"data: {json.dumps(err_payload)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                if target_idx > 0:
                    self.metrics.inc_fallbacks(
                        target_provider=provider.name,
                        source_provider=all_targets[target_idx - 1].provider_name,
                    )
                    with tracer.start_as_current_span("provider.fallback") as fb_span:
                        safe_set_attribute(fb_span, "tollgate.provider.fallback", True)
                        safe_set_attribute(
                            fb_span,
                            "tollgate.fallback.from_provider",
                            all_targets[target_idx - 1].provider_name,
                        )
                        safe_set_attribute(fb_span, "tollgate.fallback.to_provider", provider.name)
                        safe_set_attribute(
                            fb_span, "tollgate.fallback.model", target.upstream_model
                        )

                for attempt in range(1, active_policy.max_attempts + 1):
                    now = time.time()
                    remaining_deadline = deadline - now
                    if remaining_deadline <= 0:
                        yield f"data: {json.dumps({'error': {'message': 'Overall request deadline exceeded', 'type': 'timeout_error', 'code': 'timeout'}})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    metadata.record_attempt(provider.name)
                    self.metrics.inc_requests(provider.name, model=target.upstream_model)

                    chunks_emitted = 0
                    attempt_failed = False
                    error_to_raise: Optional[Exception] = None

                    with tracer.start_as_current_span("provider.attempt") as attempt_span:
                        safe_set_attribute(attempt_span, "tollgate.provider", provider.name)
                        safe_set_attribute(attempt_span, "tollgate.model", target.upstream_model)
                        safe_set_attribute(attempt_span, "tollgate.provider.attempt", attempt)
                        if circuit_decision and circuit_decision.is_probe:
                            safe_set_attribute(attempt_span, "tollgate.circuit.probe", True)
                        ttft_recorded = False
                        attempt_start = time.perf_counter()

                        try:
                            stream_iter = provider.stream(
                                request, target.upstream_model, request_id
                            )
                            async for chunk in stream_iter:
                                chunks_emitted += 1
                                if not ttft_recorded:
                                    ttft_s = time.perf_counter() - attempt_start
                                    safe_set_attribute(
                                        attempt_span,
                                        "tollgate.time_to_first_token_ms",
                                        ttft_s * 1000.0,
                                    )
                                    record_stream_ttft(
                                        provider=provider.name,
                                        model=target.upstream_model,
                                        ttft_seconds=ttft_s,
                                    )
                                    ttft_recorded = True
                                chunk_json = chunk.model_dump_json(exclude_none=True)
                                yield f"data: {chunk_json}\n\n"

                            # Successfully finished stream!
                            stream_dur_s = time.perf_counter() - attempt_start
                            safe_set_attribute(
                                attempt_span,
                                "tollgate.stream_duration_ms",
                                stream_dur_s * 1000.0,
                            )
                            safe_set_attribute(
                                attempt_span, "tollgate.chunks_emitted", chunks_emitted
                            )
                            safe_set_attribute(attempt_span, "status", "success")
                            record_stream_duration(
                                provider=provider.name,
                                model=target.upstream_model,
                                duration_seconds=stream_dur_s,
                                status="success",
                            )
                            yield "data: [DONE]\n\n"
                            self.health.record_success(provider.name)

                            # Circuit breaker: record success
                            if self.circuit_breaker:
                                await self.circuit_breaker.record_success(
                                    provider.name, target.upstream_model
                                )
                                if circuit_decision and circuit_decision.is_probe:
                                    record_circuit_half_open_probe(
                                        provider.name, target.upstream_model, "success"
                                    )
                            return

                        except asyncio.CancelledError:
                            logger.info(f"Stream cancelled by client for request {request_id}")
                            dur_s = time.perf_counter() - attempt_start
                            safe_set_attribute(attempt_span, "status", "client_cancelled")
                            record_stream_failure("client_disconnect")
                            record_stream_duration(
                                provider=provider.name,
                                model=target.upstream_model,
                                duration_seconds=dur_s,
                                status="client_disconnect",
                            )
                            raise
                        except Exception as e:
                            attempt_failed = True
                            error_to_raise = e
                            dur_s = time.perf_counter() - attempt_start
                            safe_set_attribute(attempt_span, "status", "failure")
                            fail_cls = (
                                "provider_failure"
                                if isinstance(e, ProviderException)
                                else "gateway_failure"
                            )
                            record_stream_failure(fail_cls)
                            record_stream_duration(
                                provider=provider.name,
                                model=target.upstream_model,
                                duration_seconds=dur_s,
                                status="error",
                            )

                    if attempt_failed and error_to_raise:
                        classified = classify_failure(error_to_raise)
                        self.metrics.inc_failures(
                            provider.name,
                            model=target.upstream_model,
                            failure_category=classified.category.value,
                        )
                        self.health.record_failure(provider.name, reason=classified.message)

                        # Circuit breaker: record failure
                        if self.circuit_breaker:
                            await self.circuit_breaker.record_failure(
                                provider.name, target.upstream_model, classified.category
                            )
                            if circuit_decision and circuit_decision.is_probe:
                                record_circuit_half_open_probe(
                                    provider.name, target.upstream_model, "failure"
                                )

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

                        self.metrics.inc_retries(provider.name, model=target.upstream_model)
                        with tracer.start_as_current_span("provider.retry") as retry_span:
                            safe_set_attribute(retry_span, "tollgate.provider", provider.name)
                            safe_set_attribute(retry_span, "tollgate.provider.retry", attempt)
                            safe_set_attribute(
                                retry_span, "failure_category", classified.category.value
                            )
                            safe_set_attribute(retry_span, "retry_delay_seconds", delay)

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
