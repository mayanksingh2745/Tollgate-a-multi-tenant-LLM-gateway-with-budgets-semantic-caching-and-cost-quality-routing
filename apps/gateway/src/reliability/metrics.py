import threading
from typing import Dict, List


class ReliabilityMetrics:
    """
    Internal metrics counters and latency tracking for provider operations.
    Acts as an internal instrumentation interface ready for future Prometheus export.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.provider_requests_total: Dict[str, int] = {}
        self.provider_failures_total: Dict[str, int] = {}
        self.provider_retries_total: Dict[str, int] = {}
        self.provider_fallbacks_total: Dict[str, int] = {}
        self.provider_timeouts_total: Dict[str, int] = {}
        self.provider_attempt_latency_ms: Dict[str, List[float]] = {}

    def inc_requests(self, provider: str):
        with self._lock:
            self.provider_requests_total[provider] = (
                self.provider_requests_total.get(provider, 0) + 1
            )

    def inc_failures(self, provider: str):
        with self._lock:
            self.provider_failures_total[provider] = (
                self.provider_failures_total.get(provider, 0) + 1
            )

    def inc_retries(self, provider: str):
        with self._lock:
            self.provider_retries_total[provider] = self.provider_retries_total.get(provider, 0) + 1

    def inc_fallbacks(self, target_provider: str):
        with self._lock:
            self.provider_fallbacks_total[target_provider] = (
                self.provider_fallbacks_total.get(target_provider, 0) + 1
            )

    def inc_timeouts(self, provider: str):
        with self._lock:
            self.provider_timeouts_total[provider] = (
                self.provider_timeouts_total.get(provider, 0) + 1
            )

    def record_latency(self, provider: str, latency_ms: float):
        with self._lock:
            if provider not in self.provider_attempt_latency_ms:
                self.provider_attempt_latency_ms[provider] = []
            self.provider_attempt_latency_ms[provider].append(latency_ms)

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
