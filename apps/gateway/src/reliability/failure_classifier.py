from enum import Enum
from typing import Optional

from gateway.src.providers.base import (
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderException,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


class FailureCategory(str, Enum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILURE = "authentication_failure"
    BAD_REQUEST = "bad_request"
    NOT_FOUND = "not_found"
    CONTENT_POLICY = "content_policy"
    INTERNAL = "internal"


class ClassifiedFailure:
    def __init__(
        self,
        category: FailureCategory,
        is_retryable: bool,
        is_fallback_eligible: bool,
        retry_after: Optional[float] = None,
        status_code: int = 502,
        message: str = "",
    ):
        self.category = category
        self.is_retryable = is_retryable
        self.is_fallback_eligible = is_fallback_eligible
        self.retry_after = retry_after
        self.status_code = status_code
        self.message = message

    def __repr__(self) -> str:
        return (
            f"ClassifiedFailure(category={self.category.value}, retryable={self.is_retryable}, "
            f"fallback={self.is_fallback_eligible}, retry_after={self.retry_after})"
        )


def classify_failure(error: Exception) -> ClassifiedFailure:
    """
    Centralized failure classification mapping exceptions and status codes
    to retryability and fallback eligibility decisions.
    """
    if isinstance(error, ProviderTimeoutError):
        return ClassifiedFailure(
            category=FailureCategory.TRANSIENT,
            is_retryable=True,
            is_fallback_eligible=True,
            status_code=504,
            message=error.message or "Upstream provider timed out",
        )

    if isinstance(error, ProviderRateLimitError):
        retry_after = getattr(error, "retry_after", None)
        return ClassifiedFailure(
            category=FailureCategory.RATE_LIMITED,
            is_retryable=True,
            is_fallback_eligible=True,
            retry_after=retry_after,
            status_code=429,
            message=error.message or "Upstream provider rate limit exceeded",
        )

    if isinstance(error, ProviderAuthenticationError):
        return ClassifiedFailure(
            category=FailureCategory.AUTHENTICATION_FAILURE,
            is_retryable=False,
            is_fallback_eligible=True,  # May fallback to another provider with valid credentials
            status_code=502,
            message=error.message or "Upstream provider authentication failed",
        )

    if isinstance(error, ModelNotFoundError):
        return ClassifiedFailure(
            category=FailureCategory.NOT_FOUND,
            is_retryable=False,
            is_fallback_eligible=False,
            status_code=404,
            message=error.message or "Model not found",
        )

    if isinstance(error, ProviderException):
        status = error.status_code
        retry_after = getattr(error, "retry_after", None)

        if status == 429:
            return ClassifiedFailure(
                category=FailureCategory.RATE_LIMITED,
                is_retryable=True,
                is_fallback_eligible=True,
                retry_after=retry_after,
                status_code=429,
                message=error.message,
            )
        elif status == 400:
            return ClassifiedFailure(
                category=FailureCategory.BAD_REQUEST,
                is_retryable=False,
                is_fallback_eligible=False,
                status_code=400,
                message=error.message,
            )
        elif status in (401, 403):
            return ClassifiedFailure(
                category=FailureCategory.AUTHENTICATION_FAILURE,
                is_retryable=False,
                is_fallback_eligible=True,
                status_code=502,
                message=error.message,
            )
        elif status == 404:
            return ClassifiedFailure(
                category=FailureCategory.NOT_FOUND,
                is_retryable=False,
                is_fallback_eligible=False,
                status_code=404,
                message=error.message,
            )
        elif status in (500, 502, 503, 504):
            return ClassifiedFailure(
                category=FailureCategory.TRANSIENT,
                is_retryable=True,
                is_fallback_eligible=True,
                status_code=status,
                message=error.message,
            )
        else:
            return ClassifiedFailure(
                category=(
                    FailureCategory.TRANSIENT if status >= 500 else FailureCategory.BAD_REQUEST
                ),
                is_retryable=(status >= 500),
                is_fallback_eligible=(status >= 500),
                status_code=status,
                message=error.message,
            )

    # General / unexpected exception
    return ClassifiedFailure(
        category=FailureCategory.INTERNAL,
        is_retryable=False,
        is_fallback_eligible=False,
        status_code=500,
        message=str(error) or "Internal gateway error",
    )
