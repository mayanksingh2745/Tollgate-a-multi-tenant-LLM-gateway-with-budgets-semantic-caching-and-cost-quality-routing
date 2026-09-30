import threading
from typing import Dict, List, Optional

from tollgate_core.observability import (
    record_provider_call,
    record_provider_fallback,
    record_provider_retry,
    record_provider_timeout,
)


class ReliabilityMetrics:
    """
    Internal metrics counters and latency tracking for provider operations.
    Connects directly to Prometheus export while maintaining backwards compatibility.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.provider_requests_total: Dict[str, int] = {}
        self.provider_failures_total: Dict[str, int] = {}
        self.provider_retries_total: Dict[str, int] = {}
        self.provider_fallbacks_total: Dict[str, int] = {}
        self.provider_timeouts_total: Dict[str, int] = {}
        self.provider_attempt_latency_ms: Dict[str, List[float]] = {}

    def inc_requests(self, provider: str, model: str = "mock-model"):
        with self._lock:
            self.provider_requests_total[provider] = (
                self.provider_requests_total.get(provider, 0) + 1
            )

    def inc_failures(
        self,
        provider: str,
        model: str = "mock-model",
        failure_category: Optional[str] = None,
        latency_ms: float = 0.0,
    ):
        with self._lock:
            self.provider_failures_total[provider] = (
                self.provider_failures_total.get(provider, 0) + 1
            )
        record_provider_call(
            provider=provider,
            model=model,
            status_code=502,
            duration_seconds=latency_ms / 1000.0,
            failure_category=failure_category,
        )

    def inc_retries(self, provider: str, model: str = "mock-model"):
        with self._lock:
            self.provider_retries_total[provider] = self.provider_retries_total.get(provider, 0) + 1
        record_provider_retry(provider=provider, model=model)

    def inc_fallbacks(self, target_provider: str, source_provider: str = "primary"):
        with self._lock:
            self.provider_fallbacks_total[target_provider] = (
                self.provider_fallbacks_total.get(target_provider, 0) + 1
            )
        record_provider_fallback(source_provider=source_provider, target_provider=target_provider)

    def inc_timeouts(self, provider: str, model: str = "mock-model"):
        with self._lock:
            self.provider_timeouts_total[provider] = (
                self.provider_timeouts_total.get(provider, 0) + 1
            )
        record_provider_timeout(provider=provider, model=model)

    def record_latency(
        self, provider: str, latency_ms: float, model: str = "mock-model", status_code: int = 200
    ):
        with self._lock:
            if provider not in self.provider_attempt_latency_ms:
                self.provider_attempt_latency_ms[provider] = []
            self.provider_attempt_latency_ms[provider].append(latency_ms)
        record_provider_call(
            provider=provider,
            model=model,
            status_code=status_code,
            duration_seconds=latency_ms / 1000.0,
        )

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "requests_total": dict(self.provider_requests_total),
                "failures_total": dict(self.provider_failures_total),
                "retries_total": dict(self.provider_retries_total),
                "fallbacks_total": dict(self.provider_fallbacks_total),
                "timeouts_total": dict(self.provider_timeouts_total),
            }

    def reset(self):
        with self._lock:
            self.provider_requests_total.clear()
            self.provider_failures_total.clear()
            self.provider_retries_total.clear()
            self.provider_fallbacks_total.clear()
            self.provider_timeouts_total.clear()
            self.provider_attempt_latency_ms.clear()


metrics = ReliabilityMetrics()
