from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from gateway.src.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)


class ProviderException(Exception):
    """Base exception for provider failures."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        error_type: str = "provider_error",
        code: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code


class ProviderTimeoutError(ProviderException):
    def __init__(self, message: str = "Upstream provider timed out"):
        super().__init__(
            message=message, status_code=504, error_type="timeout_error", code="timeout"
        )


class ProviderAuthenticationError(ProviderException):
    def __init__(self, message: str = "Upstream provider authentication failed"):
        super().__init__(
            message=message,
            status_code=502,
            error_type="upstream_authentication_error",
            code="provider_auth_error",
        )


class ProviderRateLimitError(ProviderException):
    def __init__(self, message: str = "Upstream provider rate limit exceeded"):
        super().__init__(
            message=message,
            status_code=429,
            error_type="upstream_rate_limit_error",
            code="provider_rate_limit",
        )


class ModelNotFoundError(ProviderException):
    def __init__(self, message: str = "Model not found"):
        super().__init__(
            message=message,
            status_code=404,
            error_type="invalid_request_error",
            code="model_not_found",
        )


class LLMProvider(ABC):
    """Abstract interface for LLM backend providers."""

    def __init__(self, name: str, base_url: str = "", api_key: str = "", timeout: float = 60.0):
        self.name = name
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    @abstractmethod
    async def chat(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion request."""
        pass

    @abstractmethod
    async def stream(
        self,
        request: ChatCompletionRequest,
        resolved_model: str,
        request_id: str,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Execute a streaming chat completion request emitting chunks."""
        pass
