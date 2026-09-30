import threading
from typing import Dict, List

from tollgate_core.observability import (
    record_worker_dead_lettered,
    record_worker_failed,
    record_worker_processed,
    record_worker_reclaimed,
)


class UsageMetrics:
    """
    Observability metrics tracker for the usage event pipeline.
    Provides thread-safe counters, gauges, and latency recordings for both gateway and worker.
    Exports to Prometheus.
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

        if metric_name == "usage_worker_events_processed_total":
            record_worker_processed("success", duration_seconds=0.005)
        elif metric_name == "usage_worker_events_failed_total":
            record_worker_failed("database_error")
        elif metric_name == "usage_worker_events_reclaimed_total":
            record_worker_reclaimed(count)
        elif metric_name == "usage_dead_letter_events_total":
            record_worker_dead_lettered("quarantined")

    def get_count(self, metric_name: str) -> int:
        with self._lock:
            return self._counters.get(metric_name, 0)

    def record_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(latency_ms)
            if len(self._latencies) > 1000:
                self._latencies = self._latencies[-1000:]
        record_worker_processed("success", duration_seconds=latency_ms / 1000.0)

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
