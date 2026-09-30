"""Thread-safe router metrics collector."""

import threading
from dataclasses import dataclass, field
from typing import List


@dataclass
class RouterMetrics:
    """
    Thread-safe in-memory metrics for the model router.
    Tracks routing decisions, latencies, and error counts.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    requests_total: int = 0
    cheap_selected_total: int = 0
    strong_selected_total: int = 0
    passthrough_total: int = 0
    fallback_total: int = 0
    inference_errors_total: int = 0
    shadow_decisions_total: int = 0

    feature_extraction_latencies: List[float] = field(default_factory=list)
    inference_latencies: List[float] = field(default_factory=list)
    confidence_scores: List[float] = field(default_factory=list)

    def record_request(self, route: str, confidence: float = 0.0, shadow: bool = False) -> None:
        with self._lock:
            self.requests_total += 1
            if shadow:
                self.shadow_decisions_total += 1
            if route == "cheap":
                self.cheap_selected_total += 1
            elif route == "strong":
                self.strong_selected_total += 1
            else:
                self.passthrough_total += 1
            if confidence > 0:
                self.confidence_scores.append(confidence)

    def record_fallback(self) -> None:
        with self._lock:
            self.fallback_total += 1

    def record_inference_error(self) -> None:
        with self._lock:
            self.inference_errors_total += 1

    def record_feature_extraction_latency(self, latency_seconds: float) -> None:
        with self._lock:
            self.feature_extraction_latencies.append(latency_seconds)

    def record_inference_latency(self, latency_seconds: float) -> None:
        with self._lock:
            self.inference_latencies.append(latency_seconds)

    def get_summary(self) -> dict:
        with self._lock:
            fe_lats = self.feature_extraction_latencies
            inf_lats = self.inference_latencies
            return {
                "requests_total": self.requests_total,
                "cheap_selected_total": self.cheap_selected_total,
                "strong_selected_total": self.strong_selected_total,
                "passthrough_total": self.passthrough_total,
                "fallback_total": self.fallback_total,
                "inference_errors_total": self.inference_errors_total,
                "shadow_decisions_total": self.shadow_decisions_total,
                "avg_feature_extraction_ms": (
                    (sum(fe_lats) / len(fe_lats)) * 1000 if fe_lats else 0.0
                ),
                "avg_inference_ms": ((sum(inf_lats) / len(inf_lats)) * 1000 if inf_lats else 0.0),
                "avg_confidence": (
                    sum(self.confidence_scores) / len(self.confidence_scores)
                    if self.confidence_scores
                    else 0.0
                ),
            }


# Global singleton
router_metrics = RouterMetrics()
