import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from gateway.src.auth.context import AuthenticatedContext
from gateway.src.auth.dependencies import get_current_api_key
from gateway.src.providers.base import ProviderException
from gateway.src.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    OpenAIErrorDetail,
    OpenAIErrorResponse,
)
from gateway.src.services.gateway_service import gateway_service

router = APIRouter(tags=["Chat Completions"])


@router.post(
    "/v1/chat/completions",
    response_model=ChatCompletionResponse,
    responses={
        200: {"description": "Successful chat completion (JSON or text/event-stream)"},
        400: {"model": OpenAIErrorResponse, "description": "Invalid request parameter"},
        401: {"description": "Authentication failure"},
        404: {"model": OpenAIErrorResponse, "description": "Unknown or unconfigured model"},
        502: {"model": OpenAIErrorResponse, "description": "Upstream provider failure"},
        504: {"model": OpenAIErrorResponse, "description": "Upstream provider timeout"},
    },
    summary="Create Chat Completion",
)
async def create_chat_completion(
    request: ChatCompletionRequest,
    raw_request: Request,
    ctx: AuthenticatedContext = Depends(get_current_api_key),
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
    }

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
            generator = gateway_service.stream_completion(
                request=request,
                ctx=ctx,
                request_id=request_id,
            )
            return StreamingResponse(
                generator,
                media_type="text/event-stream",
                headers=headers,
            )
        else:
            # Standard non-streaming response
            response = await gateway_service.chat_completion(
                request=request,
                ctx=ctx,
                request_id=request_id,
            )
            return JSONResponse(
                content=response.model_dump(exclude_none=True),
                headers=headers,
            )

    except ProviderException as pe:
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
