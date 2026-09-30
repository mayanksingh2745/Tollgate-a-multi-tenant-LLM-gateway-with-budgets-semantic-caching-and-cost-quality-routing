"""Reliability layer package for retries, backoff, health tracking, and failover."""

from gateway.src.reliability.backoff import BackoffStrategy
from gateway.src.reliability.circuit_breaker import (
    CircuitBreakerException,
    CircuitBreakerRegistry,
    CircuitBreakerState,
    CircuitDecision,
    CircuitState,
    circuit_breaker_registry,
    create_circuit_breaker_registry_from_settings,
    make_provider_key,
)
from gateway.src.reliability.executor import ExecutionMetadata, ReliableExecutor
from gateway.src.reliability.failure_classifier import FailureCategory, classify_failure
from gateway.src.reliability.health import ProviderHealthTracker, health_tracker
from gateway.src.reliability.metrics import ReliabilityMetrics, metrics
from gateway.src.reliability.policy import (
    FallbackRoute,
    ProviderTarget,
    ReliabilityPolicy,
)

__all__ = [
    "BackoffStrategy",
    "ExecutionMetadata",
    "ReliableExecutor",
    "FailureCategory",
    "classify_failure",
    "ProviderHealthTracker",
    "health_tracker",
    "ReliabilityMetrics",
    "metrics",
    "FallbackRoute",
    "ProviderTarget",
    "ReliabilityPolicy",
    "CircuitState",
    "CircuitDecision",
    "CircuitBreakerException",
    "CircuitBreakerState",
    "CircuitBreakerRegistry",
    "circuit_breaker_registry",
    "create_circuit_breaker_registry_from_settings",
    "make_provider_key",
]
