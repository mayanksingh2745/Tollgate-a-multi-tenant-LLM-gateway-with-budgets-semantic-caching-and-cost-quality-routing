import asyncio
import json
import logging
import time
from typing import AsyncIterator

from gateway.src.auth.context import AuthenticatedContext
from gateway.src.providers.base import LLMProvider
from gateway.src.providers.registry import provider_registry
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

logger = logging.getLogger("tollgate.gateway_service")


class GatewayService:
    def __init__(self, registry=None):
        self.registry = registry or provider_registry

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        ctx: AuthenticatedContext,
        request_id: str,
    ) -> ChatCompletionResponse:
        t0 = time.perf_counter()

        resolution = self.registry.resolve_model(request.model)
        provider: LLMProvider = resolution.provider

        try:
            response = await provider.chat(
                request=request,
                resolved_model=resolution.upstream_model,
                request_id=request_id,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            # Safe structured audit/request logging (no prompts, no responses, no credentials)
            logger.info(
                f"Gateway Request Completed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"project_id={ctx.project_id} api_key_id={ctx.api_key_id} model={request.model} "
                f"provider={provider.name} stream=false latency_ms={latency_ms:.2f} status=200"
            )

            return response
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            status_code = getattr(e, "status_code", 500)
            logger.warning(
                f"Gateway Request Failed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"project_id={ctx.project_id} model={request.model} provider={provider.name} "
                f"stream=false latency_ms={latency_ms:.2f} status={status_code} error={e}"
            )
            raise

    async def stream_completion(
        self,
        request: ChatCompletionRequest,
        ctx: AuthenticatedContext,
        request_id: str,
    ) -> AsyncIterator[str]:
        t0 = time.perf_counter()

        resolution = self.registry.resolve_model(request.model)
        provider: LLMProvider = resolution.provider

        chunk_count = 0
        try:
            stream_gen = provider.stream(
                request=request,
                resolved_model=resolution.upstream_model,
                request_id=request_id,
            )

            async for chunk in stream_gen:
                chunk_count += 1
                chunk_json = chunk.model_dump_json(exclude_none=True)
                yield f"data: {chunk_json}\n\n"

            # Terminal SSE token
            yield "data: [DONE]\n\n"

            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(
                f"Gateway Stream Completed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"project_id={ctx.project_id} api_key_id={ctx.api_key_id} model={request.model} "
                f"provider={provider.name} stream=true chunks={chunk_count} latency_ms={latency_ms:.2f} status=200"
            )
        except asyncio.CancelledError:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(
                f"Gateway Stream Disconnected: Client cancelled request_id={request_id} "
                f"after {chunk_count} chunks latency_ms={latency_ms:.2f}"
            )
            raise
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            status_code = getattr(e, "status_code", 500)
            logger.warning(
                f"Gateway Stream Failed: request_id={request_id} tenant_id={ctx.tenant_id} "
                f"model={request.model} provider={provider.name} latency_ms={latency_ms:.2f} "
                f"status={status_code} error={e}"
            )
            # Emit error chunk or let HTTP layer handle
            error_payload = {
                "error": {
                    "message": str(e),
                    "type": getattr(e, "error_type", "provider_error"),
                    "code": getattr(e, "code", "provider_error"),
                }
            }
            yield f"data: {json.dumps(error_payload)}\n\n"
            yield "data: [DONE]\n\n"


gateway_service = GatewayService()
