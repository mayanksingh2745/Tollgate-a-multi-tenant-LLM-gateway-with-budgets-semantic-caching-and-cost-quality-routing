import threading
from typing import Dict, List


class UsageMetrics:
    """
    Observability metrics tracker for the usage event pipeline.
    Provides thread-safe counters, gauges, and latency recordings for both gateway and worker.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "usage_events_published_total": 0,
            "usage_event_publish_failures_total": 0,
            "usage_worker_events_processed_total": 0,
            "usage_worker_events_failed_total": 0,
            "usage_worker_events_retried_total": 0,
            "usage_worker_events_reclaimed_total": 0,
            "usage_dead_letter_events_total": 0,
            "usage_event_duplicate_total": 0,
        }
        self._latencies: List[float] = []
        self._batch_sizes: List[int] = []

    def increment(self, metric_name: str, count: int = 1) -> None:
        with self._lock:
            if metric_name in self._counters:
                self._counters[metric_name] += count
            else:
                self._counters[metric_name] = count

    def get_count(self, metric_name: str) -> int:
        with self._lock:
            return self._counters.get(metric_name, 0)

    def record_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(latency_ms)
            if len(self._latencies) > 1000:
                self._latencies = self._latencies[-1000:]

    def record_batch_size(self, size: int) -> None:
        with self._lock:
            self._batch_sizes.append(size)
            if len(self._batch_sizes) > 1000:
                self._batch_sizes = self._batch_sizes[-1000:]

    def get_all(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0
            self._latencies.clear()
            self._batch_sizes.clear()


usage_metrics = UsageMetrics()
