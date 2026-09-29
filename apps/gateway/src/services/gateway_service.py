import logging
import time
from typing import AsyncIterator, Optional, Tuple

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.registry import provider_registry
from gateway.src.reliability.executor import ExecutionMetadata, ReliableExecutor
from gateway.src.reliability.policy import ReliabilityPolicy
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

logger = logging.getLogger("tollgate.gateway_service")


class GatewayService:
    def __init__(self, registry=None, executor=None):
        self.registry = registry or provider_registry
        self.executor = executor or ReliableExecutor()

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        ctx: AuthenticatedContext,
        request_id: str,
        policy: Optional[ReliabilityPolicy] = None,
    ) -> Tuple[ChatCompletionResponse, ExecutionMetadata]:
        t0 = time.perf_counter()

        # Resolve deterministic primary and fallback route
        route = self.registry.get_route(request.model)
        providers_map = self.registry.get_all_providers()

        try:
            response, metadata = await self.executor.execute_chat(
                request=request,
                route=route,
                providers_map=providers_map,
                ctx=ctx,
                request_id=request_id,
                policy=policy,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            metadata.latency_ms = latency_ms

            # Safe structured audit/request logging (no prompts, no responses, no credentials)
            logger.info(
                f"Gateway Request Completed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"project_id={ctx.project_id} api_key_id={ctx.api_key_id} model={request.model} "
                f"provider={metadata.final_provider} attempts={metadata.total_attempts} "
                f"fallback_used={metadata.fallback_used} stream=false latency_ms={latency_ms:.2f} status=200"
            )

            return response, metadata

        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            status_code = getattr(e, "status_code", 500)
            logger.warning(
                f"Gateway Request Failed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"project_id={ctx.project_id} model={request.model} stream=false "
                f"latency_ms={latency_ms:.2f} status={status_code} error={e}"
            )
            raise

    async def stream_completion(
        self,
        request: ChatCompletionRequest,
        ctx: AuthenticatedContext,
        request_id: str,
        policy: Optional[ReliabilityPolicy] = None,
    ) -> AsyncIterator[str]:
        route = self.registry.get_route(request.model)
        providers_map = self.registry.get_all_providers()

        generator = self.executor.execute_stream(
            request=request,
            route=route,
            providers_map=providers_map,
            ctx=ctx,
            request_id=request_id,
            policy=policy,
        )

        async for chunk in generator:
            yield chunk


from gateway.src.reliability.health import health_tracker
from gateway.src.reliability.metrics import metrics

gateway_service = GatewayService(
    executor=ReliableExecutor(health=health_tracker, metric_recorder=metrics)
)
