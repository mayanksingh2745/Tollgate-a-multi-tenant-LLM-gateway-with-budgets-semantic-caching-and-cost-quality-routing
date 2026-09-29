import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.budgets import (
    BudgetExceededError,
    budget_manager,
    estimate_prompt_tokens,
    estimate_request_cost,
    pricing_service,
)
from gateway.src.db import get_db
from gateway.src.providers.base import ProviderException
from gateway.src.ratelimit import RateLimitResult, rate_limit_dependency
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    OpenAIErrorDetail,
    OpenAIErrorResponse,
)
from gateway.src.services.budget_service import get_effective_budget_limits
from gateway.src.services.gateway_service import gateway_service
from gateway.src.usage.publisher import usage_publisher
from sqlalchemy.ext.asyncio import AsyncSession
from tollgate_core.usage import UsageEventPayload

router = APIRouter(tags=["Chat Completions"])


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    responses={
        200: {"description": "Successful chat completion (JSON or text/event-stream)"},
        400: {"model": OpenAIErrorResponse, "description": "Invalid request parameter"},
        401: {"description": "Authentication failure"},
        402: {"model": OpenAIErrorResponse, "description": "Budget exceeded"},
        404: {"model": OpenAIErrorResponse, "description": "Unknown or unconfigured model"},
        429: {"model": OpenAIErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": OpenAIErrorResponse, "description": "Upstream provider failure"},
        504: {"model": OpenAIErrorResponse, "description": "Upstream provider timeout"},
    },
    summary="Create Chat Completion",
)
async def create_chat_completion(
    request: ChatCompletionRequest,
    raw_request: Request,
    ctx: AuthenticatedContext = Depends(get_current_api_key),
    rate_limit: RateLimitResult = Depends(rate_limit_dependency),
    db: AsyncSession = Depends(get_db),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    """
    OpenAI-compatible chat completion gateway endpoint.
    Supports both non-streaming responses and incremental SSE streaming.
    """
    # 1. Resolve or generate Request ID
    request_id = x_request_id or f"req_{uuid.uuid4().hex[:16]}"

    headers = {
        "X-Request-ID": request_id,
        **rate_limit.headers,
    }

    # 2. Atomic Budget Reservation (Multi-scope: Tenant + Project)
    limits = await get_effective_budget_limits(
        db=db, tenant_id=ctx.tenant_id, project_id=ctx.project_id
    )
    estimated_cost = estimate_request_cost(request)

    reservation = await budget_manager.reserve(
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        estimated_cost=estimated_cost,
        limits=limits,
        reservation_id=request_id,
    )
    if not reservation.allowed:
        raise BudgetExceededError(
            f"Budget exceeded for {reservation.scope or 'account'}. Insufficient spending balance.",
            scope=reservation.scope,
        )

    try:
        if request.stream:
            # SSE streaming response
            headers.update(
                {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
            raw_generator = gateway_service.stream_completion(
                request=request,
                ctx=ctx,
                request_id=request_id,
            )

            async def stream_with_budget():
                prompt_tokens = estimate_prompt_tokens(request.messages)
                output_tokens = 0
                chunks_emitted = 0
                t0_stream = time.perf_counter()
                route = gateway_service.registry.get_route(request.model)
                stream_provider = (
                    route.primary.provider_name if route and route.primary else "openai"
                )
                try:
                    async for chunk in raw_generator:
                        chunks_emitted += 1
                        output_tokens += 1
                        yield chunk

                    actual_cost = pricing_service.calculate_cost(
                        model=request.model,
                        input_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        provider=stream_provider,
                    )
                    await budget_manager.settle(reservation.reservation_id, actual_cost)
                    stream_latency_ms = (time.perf_counter() - t0_stream) * 1000.0

                    usage_event = UsageEventPayload(
                        request_id=request_id,
                        reservation_id=reservation.reservation_id,
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        api_key_id=ctx.api_key_id,
                        provider=stream_provider,
                        model=request.model,
                        stream=True,
                        status="success",
                        input_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        total_tokens=prompt_tokens + output_tokens,
                        estimated_cost=reservation.estimated_cost,
                        actual_cost=actual_cost,
                        latency_ms=stream_latency_ms,
                        attempt_count=1,
                        fallback_used=False,
                    )
                    await usage_publisher.publish(usage_event)
                except Exception as e:
                    stream_latency_ms = (time.perf_counter() - t0_stream) * 1000.0
                    if chunks_emitted == 0:
                        await budget_manager.release(reservation.reservation_id)
                    else:
                        actual_cost = pricing_service.calculate_cost(
                            model=request.model,
                            input_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            provider=stream_provider,
                        )
                        await budget_manager.settle(reservation.reservation_id, actual_cost)
                        usage_event = UsageEventPayload(
                            request_id=request_id,
                            reservation_id=reservation.reservation_id,
                            tenant_id=ctx.tenant_id,
                            project_id=ctx.project_id,
                            api_key_id=ctx.api_key_id,
                            provider=stream_provider,
                            model=request.model,
                            stream=True,
                            status=(
                                "provider_failure"
                                if isinstance(e, ProviderException)
                                else "client_cancelled"
                            ),
                            input_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            total_tokens=prompt_tokens + output_tokens,
                            estimated_cost=reservation.estimated_cost,
                            actual_cost=actual_cost,
                            latency_ms=stream_latency_ms,
                            attempt_count=1,
                            fallback_used=False,
                        )
                        await usage_publisher.publish(usage_event)
                    raise

            return StreamingResponse(
                stream_with_budget(),
                media_type="text/event-stream",
                headers=headers,
            )
        else:
            # Standard non-streaming response
            response, metadata = await gateway_service.chat_completion(
                request=request,
                ctx=ctx,
                request_id=request_id,
            )

            # Calculate actual usage and settle reservation
            actual_in = response.usage.prompt_tokens if response.usage else 0
            actual_out = response.usage.completion_tokens if response.usage else 0
            actual_cost = pricing_service.calculate_cost(
                model=request.model,
                input_tokens=actual_in,
                output_tokens=actual_out,
                provider=metadata.final_provider,
            )
            await budget_manager.settle(reservation.reservation_id, actual_cost)

            # Publish usage event to Redis Stream (non-blocking, asynchronous)
            usage_event = UsageEventPayload(
                request_id=request_id,
                reservation_id=reservation.reservation_id,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                api_key_id=ctx.api_key_id,
                provider=metadata.final_provider or "unknown",
                model=request.model,
                stream=False,
                status="success",
                input_tokens=actual_in,
                output_tokens=actual_out,
                total_tokens=actual_in + actual_out,
                estimated_cost=reservation.estimated_cost,
                actual_cost=actual_cost,
                latency_ms=getattr(metadata, "latency_ms", 0.0),
                attempt_count=metadata.total_attempts,
                fallback_used=metadata.fallback_used,
            )
            await usage_publisher.publish(usage_event)

            if metadata.final_provider:
                headers["X-Tollgate-Provider"] = metadata.final_provider
            headers["X-Tollgate-Attempts"] = str(metadata.total_attempts)
            headers["X-Tollgate-Fallback"] = "true" if metadata.fallback_used else "false"

            return JSONResponse(
                content=response.model_dump(exclude_none=True),
                headers=headers,
            )

    except ProviderException as pe:
        await budget_manager.release(reservation.reservation_id)
        return JSONResponse(
            status_code=pe.status_code,
            headers=headers,
            content=OpenAIErrorResponse(
                error=OpenAIErrorDetail(
                    message=pe.message,
                    type=pe.error_type,
                    code=pe.code,
                )
            ).model_dump(),
        )
    except Exception:
        await budget_manager.release(reservation.reservation_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers=headers,
            content=OpenAIErrorResponse(
                error=OpenAIErrorDetail(
                    message="Internal gateway error occurred.",
                    type="internal_gateway_error",
                    code="server_error",
                )
            ).model_dump(),
        )
