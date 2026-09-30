import threading
from typing import Dict, List


from tollgate_core.observability import (
    record_cache_error,
    record_cache_operation,
    record_cache_request,
    record_cache_similarity,
)


class SemanticCacheMetrics:
    """
    In-memory metrics collector for semantic cache observability.
    Thread-safe and compatible with Prometheus exposition format.
    Never exposes raw prompts or unbounded cardinality labels.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "semantic_cache_requests_total": 0,
            "semantic_cache_hits_total": 0,
            "semantic_cache_misses_total": 0,
            "semantic_cache_bypasses_total": 0,
            "semantic_cache_errors_total": 0,
            "semantic_cache_embedding_requests_total": 0,
            "semantic_cache_embedding_errors_total": 0,
        }
        self._lookup_latencies_ms: List[float] = []
        self._embedding_latencies_ms: List[float] = []
        self._write_latencies_ms: List[float] = []
        self._similarity_scores: List[float] = []

    def increment(self, counter_name: str, amount: int = 1) -> None:
        with self._lock:
            if counter_name in self._counters:
                self._counters[counter_name] += amount
            else:
                self._counters[counter_name] = amount

        if counter_name == "semantic_cache_hits_total":
            record_cache_request("semantic", "hit")
        elif counter_name == "semantic_cache_misses_total":
            record_cache_request("semantic", "miss")
        elif counter_name == "semantic_cache_bypasses_total":
            record_cache_request("semantic", "bypass")
        elif counter_name == "semantic_cache_errors_total":
            record_cache_error("semantic", "lookup")
        elif counter_name == "semantic_cache_embedding_errors_total":
            record_cache_error("semantic", "embed")

    def record_lookup_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._lookup_latencies_ms.append(latency_ms)
            if len(self._lookup_latencies_ms) > 2000:
                self._lookup_latencies_ms.pop(0)
        record_cache_operation("semantic", "lookup", latency_ms / 1000.0)

    def record_embedding_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._embedding_latencies_ms.append(latency_ms)
            if len(self._embedding_latencies_ms) > 2000:
                self._embedding_latencies_ms.pop(0)
        record_cache_operation("semantic", "embed", latency_ms / 1000.0)

    def record_write_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._write_latencies_ms.append(latency_ms)
            if len(self._write_latencies_ms) > 2000:
                self._write_latencies_ms.pop(0)
        record_cache_operation("semantic", "store", latency_ms / 1000.0)

    def record_similarity_score(self, score: float) -> None:
        with self._lock:
            self._similarity_scores.append(score)
            if len(self._similarity_scores) > 2000:
                self._similarity_scores.pop(0)
        record_cache_similarity(score, "semantic")

    def get_stats(self) -> Dict[str, object]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "lookup_latency_count": len(self._lookup_latencies_ms),
                "embedding_latency_count": len(self._embedding_latencies_ms),
                "write_latency_count": len(self._write_latencies_ms),
                "similarity_score_count": len(self._similarity_scores),
            }

    def reset(self) -> None:
        with self._lock:
            for k in self._counters:
                self._counters[k] = 0
            self._lookup_latencies_ms.clear()
            self._embedding_latencies_ms.clear()
            self._write_latencies_ms.clear()
            self._similarity_scores.clear()


semantic_cache_metrics = SemanticCacheMetrics()
