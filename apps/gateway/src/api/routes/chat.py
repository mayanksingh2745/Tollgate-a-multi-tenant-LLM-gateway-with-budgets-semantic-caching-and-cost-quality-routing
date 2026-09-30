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
from gateway.src.cache import Canonicalizer, exact_cache, semantic_cache
from gateway.src.config import settings
from gateway.src.db import get_db
from gateway.src.providers.base import ProviderException
from gateway.src.ratelimit import RateLimitResult, rate_limit_dependency
from gateway.src.router import model_router
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
from tollgate_core.observability import (
    current_request_id,
    get_current_span_id,
    get_current_trace_id,
    get_current_traceparent,
    get_tracer,
    record_error,
    safe_set_attribute,
)
from tollgate_core.usage import UsageEventPayload

tracer = get_tracer("tollgate.gateway")

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
    Integrates rate limiting, exact response caching, budget enforcement, and usage accounting.
    """
    # 1. Resolve or generate Request ID
    request_id = x_request_id or current_request_id.get() or f"req_{uuid.uuid4().hex[:16]}"
    current_request_id.set(request_id)

    headers = {
        "X-Request-ID": request_id,
        **rate_limit.headers,
    }
    trace_id = get_current_trace_id()
    if trace_id:
        headers["X-Trace-ID"] = trace_id
    tp = get_current_traceparent()
    if tp:
        headers["traceparent"] = tp

    from opentelemetry import trace

    active_span = trace.get_current_span()
    if active_span and active_span.is_recording():
        safe_set_attribute(active_span, "tollgate.request_id", request_id)
        safe_set_attribute(active_span, "tollgate.tenant_id", str(ctx.tenant_id))
        safe_set_attribute(active_span, "tollgate.project_id", str(ctx.project_id))
        safe_set_attribute(active_span, "tollgate.requested_model", request.model)
        safe_set_attribute(active_span, "tollgate.stream", bool(request.stream))

    reservation = None
    routing_decision = None
    try:
        # Resolve deterministic primary provider
        route = gateway_service.registry.get_route(request.model)
        provider_name = route.primary.provider_name if route and route.primary else "openai"

        # 2. Exact Cache Lookup (evaluated before budget reservation to avoid consuming budget on hit)
        with tracer.start_as_current_span("cache.lookup") as c_span:
            safe_set_attribute(c_span, "cache.type", "exact")
            safe_set_attribute(c_span, "tollgate.cache.type", "exact")
            cached_response = await exact_cache.get(
                request=request,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                provider=provider_name,
            )
            hit = cached_response is not None
            safe_set_attribute(c_span, "cache.hit", hit)
            safe_set_attribute(c_span, "tollgate.cache.hit", hit)

        if cached_response is not None:
            if active_span and active_span.is_recording():
                safe_set_attribute(active_span, "tollgate.cache.type", "exact")
                safe_set_attribute(active_span, "tollgate.cache.hit", True)
            if settings.cache_header_enabled:
                headers["X-Tollgate-Cache"] = "HIT"
            headers["X-Tollgate-Provider"] = provider_name
            return JSONResponse(
                content=cached_response.model_dump(exclude_none=True),
                headers=headers,
            )

        # 2b. Semantic Cache Lookup (evaluated when exact cache misses)
        with tracer.start_as_current_span("cache.lookup") as sc_span:
            safe_set_attribute(sc_span, "cache.type", "semantic")
            safe_set_attribute(sc_span, "tollgate.cache.type", "semantic")
            semantic_response, _ = await semantic_cache.get(
                request=request,
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                provider=provider_name,
                session=db,
            )
            hit = semantic_response is not None
            safe_set_attribute(sc_span, "cache.hit", hit)
            safe_set_attribute(sc_span, "tollgate.cache.hit", hit)

        if semantic_response is not None:
            if active_span and active_span.is_recording():
                safe_set_attribute(active_span, "tollgate.cache.type", "semantic")
                safe_set_attribute(active_span, "tollgate.cache.hit", True)
            if settings.cache_header_enabled:
                headers["X-Tollgate-Cache"] = "SEMANTIC_HIT"
            headers["X-Tollgate-Provider"] = provider_name
            return JSONResponse(
                content=semantic_response.model_dump(exclude_none=True),
                headers=headers,
            )

        if active_span and active_span.is_recording():
            safe_set_attribute(active_span, "tollgate.cache.hit", False)

        if settings.cache_header_enabled:
            is_cacheable, bypass_reason = Canonicalizer.is_cacheable(request)
            headers["X-Tollgate-Cache"] = "BYPASS" if not is_cacheable else "MISS"
            if not is_cacheable and bypass_reason and active_span and active_span.is_recording():
                safe_set_attribute(active_span, "cache.bypass_reason", bypass_reason)

        # 2c. Model Router Evaluation (evaluated on cache miss, before budget reservation)
        with tracer.start_as_current_span("router.decision") as r_span:
            routing_decision = await model_router.route(request)
            mode = settings.router_mode if settings.router_enabled else "disabled"
            safe_set_attribute(r_span, "router.mode", mode)
            safe_set_attribute(r_span, "tollgate.router.mode", mode)
            safe_set_attribute(r_span, "router.route", routing_decision.route)
            safe_set_attribute(r_span, "tollgate.router.route", routing_decision.route)
            safe_set_attribute(r_span, "router.confidence", routing_decision.confidence)
            safe_set_attribute(r_span, "tollgate.router.confidence", routing_decision.confidence)
            if hasattr(routing_decision, "threshold") and routing_decision.threshold is not None:
                safe_set_attribute(r_span, "router.threshold", routing_decision.threshold)
            safe_set_attribute(
                r_span, "requested_model", routing_decision.original_model or request.model
            )
            safe_set_attribute(r_span, "selected_model", routing_decision.selected_model)
            if active_span and active_span.is_recording():
                safe_set_attribute(active_span, "tollgate.router.mode", mode)
                safe_set_attribute(active_span, "tollgate.router.route", routing_decision.route)

        if settings.router_enabled and settings.router_mode != "disabled":
            headers["X-Tollgate-Router-Route"] = routing_decision.route
            headers["X-Tollgate-Router-Selected-Model"] = routing_decision.selected_model
            headers["X-Tollgate-Router-Confidence"] = f"{routing_decision.confidence:.4f}"
            if routing_decision.shadow:
                headers["X-Tollgate-Router-Shadow"] = "true"
            if routing_decision.fallback:
                headers["X-Tollgate-Router-Fallback"] = "true"

        # Apply routing if not in shadow mode
        if not routing_decision.shadow and routing_decision.selected_model != request.model:
            request.model = routing_decision.selected_model
            route = gateway_service.registry.get_route(request.model)
            provider_name = route.primary.provider_name if route and route.primary else "openai"

        # 3. Atomic Budget Reservation (Multi-scope: Tenant + Project)
        with tracer.start_as_current_span("budget.reserve") as b_res_span:
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
            safe_set_attribute(b_res_span, "budget.allowed", reservation.allowed)
            if reservation.scope:
                safe_set_attribute(b_res_span, "budget.scope", reservation.scope)
            safe_set_attribute(b_res_span, "reservation_id", reservation.reservation_id)

        if not reservation.allowed:
            raise BudgetExceededError(
                f"Budget exceeded for {reservation.scope or 'account'}. Insufficient spending balance.",
                scope=reservation.scope,
            )
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
                    with tracer.start_as_current_span("budget.settle") as b_settle_span:
                        safe_set_attribute(
                            b_settle_span, "reservation_id", reservation.reservation_id
                        )
                        await budget_manager.settle(reservation.reservation_id, actual_cost)
                        safe_set_attribute(b_settle_span, "budget.settled", True)

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
                        router_mode=(
                            settings.router_mode if settings.router_enabled else "disabled"
                        ),
                        router_route=(routing_decision.route if routing_decision else None),
                        router_confidence=(
                            routing_decision.confidence
                            if routing_decision and routing_decision.confidence > 0
                            else None
                        ),
                        router_model_version=(
                            routing_decision.model_version if routing_decision else None
                        ),
                        router_fallback=(routing_decision.fallback if routing_decision else False),
                        original_model=(
                            routing_decision.original_model
                            if (routing_decision and routing_decision.original_model)
                            else request.model
                        ),
                        cache_status=headers.get("X-Tollgate-Cache", "MISS"),
                        traceparent=get_current_traceparent(),
                        trace_id=get_current_trace_id(),
                        span_id=get_current_span_id(),
                    )
                    with tracer.start_as_current_span("usage.publish") as up_span:
                        safe_set_attribute(up_span, "tollgate.request_id", request_id)
                        safe_set_attribute(up_span, "tollgate.stream", True)
                        await usage_publisher.publish(usage_event)
                except Exception as e:
                    stream_latency_ms = (time.perf_counter() - t0_stream) * 1000.0
                    if chunks_emitted == 0:
                        with tracer.start_as_current_span("budget.release") as b_rel_span:
                            safe_set_attribute(
                                b_rel_span, "reservation_id", reservation.reservation_id
                            )
                            await budget_manager.release(reservation.reservation_id)
                            safe_set_attribute(b_rel_span, "budget.released", True)
                    else:
                        actual_cost = pricing_service.calculate_cost(
                            model=request.model,
                            input_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            provider=stream_provider,
                        )
                        with tracer.start_as_current_span("budget.settle") as b_settle_span:
                            safe_set_attribute(
                                b_settle_span, "reservation_id", reservation.reservation_id
                            )
                            await budget_manager.settle(reservation.reservation_id, actual_cost)
                            safe_set_attribute(b_settle_span, "budget.settled", True)

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
                            router_mode=(
                                settings.router_mode if settings.router_enabled else "disabled"
                            ),
                            router_route=(routing_decision.route if routing_decision else None),
                            router_confidence=(
                                routing_decision.confidence
                                if routing_decision and routing_decision.confidence > 0
                                else None
                            ),
                            router_model_version=(
                                routing_decision.model_version if routing_decision else None
                            ),
                            router_fallback=(
                                routing_decision.fallback if routing_decision else False
                            ),
                            original_model=(
                                routing_decision.original_model
                                if (routing_decision and routing_decision.original_model)
                                else request.model
                            ),
                            cache_status=headers.get("X-Tollgate-Cache", "MISS"),
                            traceparent=get_current_traceparent(),
                            trace_id=get_current_trace_id(),
                            span_id=get_current_span_id(),
                        )
                        with tracer.start_as_current_span("usage.publish") as up_span:
                            safe_set_attribute(up_span, "tollgate.request_id", request_id)
                            safe_set_attribute(up_span, "tollgate.stream", True)
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
            with tracer.start_as_current_span("budget.settle") as b_settle_span:
                safe_set_attribute(b_settle_span, "reservation_id", reservation.reservation_id)
                await budget_manager.settle(reservation.reservation_id, actual_cost)
                safe_set_attribute(b_settle_span, "budget.settled", True)

            # Store in exact & semantic response cache
            with tracer.start_as_current_span("cache.write") as cw_span:
                safe_set_attribute(cw_span, "cache.type", "exact_and_semantic")
                safe_set_attribute(cw_span, "tollgate.cache.type", "exact_and_semantic")
                final_prov = metadata.final_provider or provider_name
                await exact_cache.set(
                    request=request,
                    response=response,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    provider=final_prov,
                )

                # Index in semantic response cache
                response_key = await exact_cache.build_cache_key(
                    request=request,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    provider=final_prov,
                )
                await semantic_cache.set(
                    request=request,
                    response=response,
                    response_cache_key=response_key,
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    provider=final_prov,
                    session=db,
                )

                # If model was rewritten from original_model, also cache under original_model
                # so subsequent requests for original_model hit exact cache directly
                if (
                    routing_decision
                    and routing_decision.original_model
                    and routing_decision.original_model != request.model
                ):
                    orig_request = request.model_copy(
                        update={"model": routing_decision.original_model}
                    )
                    orig_route = gateway_service.registry.get_route(routing_decision.original_model)
                    orig_prov = (
                        orig_route.primary.provider_name
                        if orig_route and orig_route.primary
                        else final_prov
                    )
                    await exact_cache.set(
                        request=orig_request,
                        response=response,
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        provider=orig_prov,
                    )
                    orig_response_key = await exact_cache.build_cache_key(
                        request=orig_request,
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        provider=orig_prov,
                    )
                    await semantic_cache.set(
                        request=orig_request,
                        response=response,
                        response_cache_key=orig_response_key,
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        provider=orig_prov,
                        session=db,
                    )

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
                router_mode=(settings.router_mode if settings.router_enabled else "disabled"),
                router_route=(routing_decision.route if routing_decision else None),
                router_confidence=(
                    routing_decision.confidence
                    if routing_decision and routing_decision.confidence > 0
                    else None
                ),
                router_model_version=(routing_decision.model_version if routing_decision else None),
                router_fallback=(routing_decision.fallback if routing_decision else False),
                original_model=(
                    routing_decision.original_model
                    if (routing_decision and routing_decision.original_model)
                    else request.model
                ),
                cache_status=headers.get("X-Tollgate-Cache", "MISS"),
                traceparent=get_current_traceparent(),
                trace_id=get_current_trace_id(),
                span_id=get_current_span_id(),
            )
            with tracer.start_as_current_span("usage.publish") as up_span:
                safe_set_attribute(up_span, "tollgate.request_id", request_id)
                safe_set_attribute(up_span, "tollgate.stream", False)
                await usage_publisher.publish(usage_event)

            if metadata.final_provider:
                headers["X-Tollgate-Provider"] = metadata.final_provider
            headers["X-Tollgate-Attempts"] = str(metadata.total_attempts)
            headers["X-Tollgate-Fallback"] = "true" if metadata.fallback_used else "false"

            return JSONResponse(
                content=response.model_dump(exclude_none=True),
                headers=headers,
            )

    except BudgetExceededError:
        if reservation and reservation.allowed:
            with tracer.start_as_current_span("budget.release") as b_rel_span:
                safe_set_attribute(b_rel_span, "reservation_id", reservation.reservation_id)
                await budget_manager.release(reservation.reservation_id)
                safe_set_attribute(b_rel_span, "budget.released", True)
        raise
    except ProviderException as pe:
        record_error(category=pe.error_type, status_code=pe.status_code)
        if reservation and reservation.allowed:
            with tracer.start_as_current_span("budget.release") as b_rel_span:
                safe_set_attribute(b_rel_span, "reservation_id", reservation.reservation_id)
                await budget_manager.release(reservation.reservation_id)
                safe_set_attribute(b_rel_span, "budget.released", True)
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
        record_error(category="internal", status_code=500)
        if reservation and reservation.allowed:
            with tracer.start_as_current_span("budget.release") as b_rel_span:
                safe_set_attribute(b_rel_span, "reservation_id", reservation.reservation_id)
                await budget_manager.release(reservation.reservation_id)
                safe_set_attribute(b_rel_span, "budget.released", True)
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
