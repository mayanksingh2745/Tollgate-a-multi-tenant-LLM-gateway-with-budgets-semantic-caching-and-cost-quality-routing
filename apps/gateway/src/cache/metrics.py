import threading
from typing import Dict, List


class CacheMetrics:
    """
    Thread-safe observability metrics tracker for Tollgate's exact response cache.
    Maintains bounded cardinality counters and latency recordings.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "cache_hits_total": 0,
            "cache_misses_total": 0,
            "cache_bypasses_total": 0,
            "cache_lookup_errors_total": 0,
            "cache_write_errors_total": 0,
            "cache_evictions_total": 0,
            "cache_response_too_large_total": 0,
        }
        self._lookup_latencies: List[float] = []
        self._write_latencies: List[float] = []

    def increment(self, metric_name: str, count: int = 1) -> None:
        with self._lock:
            if metric_name in self._counters:
                self._counters[metric_name] += count
            else:
                self._counters[metric_name] = count

    def get_count(self, metric_name: str) -> int:
        with self._lock:
            return self._counters.get(metric_name, 0)

    def record_lookup_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._lookup_latencies.append(latency_ms)
            if len(self._lookup_latencies) > 1000:
                self._lookup_latencies = self._lookup_latencies[-1000:]

    def record_write_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._write_latencies.append(latency_ms)
            if len(self._write_latencies) > 1000:
                self._write_latencies = self._write_latencies[-1000:]

    def get_all(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0
            self._lookup_latencies.clear()
            self._write_latencies.clear()


cache_metrics = CacheMetrics()
