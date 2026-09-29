from dataclasses import dataclass, field
from typing import List

from gateway.src.config import settings


@dataclass
class ProviderTarget:
    provider_name: str
    upstream_model: str


@dataclass
class FallbackRoute:
    logical_model: str
    primary: ProviderTarget
    fallbacks: List[ProviderTarget] = field(default_factory=list)


@dataclass
class ReliabilityPolicy:
    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 5.0
    jitter: bool = True
    overall_timeout_seconds: float = 60.0
    provider_timeout_seconds: float = 30.0

    @classmethod
    def from_settings(cls) -> "ReliabilityPolicy":
        return cls(
            max_attempts=settings.max_retries,
            base_delay=settings.retry_base_delay,
            max_delay=settings.retry_max_delay,
            jitter=settings.retry_jitter,
            overall_timeout_seconds=settings.request_timeout_seconds,
            provider_timeout_seconds=settings.provider_timeout_seconds,
        )
