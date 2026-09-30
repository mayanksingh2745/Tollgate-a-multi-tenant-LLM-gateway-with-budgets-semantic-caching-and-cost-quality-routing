"""
Circuit Breaker for Tollgate Provider Reliability.

Production-grade circuit breaker with three states (CLOSED, OPEN, HALF_OPEN),
windowed failure tracking, probe-limited half-open recovery, and bounded
Prometheus metrics.

Design decisions:
- Scope: provider+model pair (e.g., "openai:gpt-4o")
- State: In-memory (single-instance architecture). A restart resets all circuits.
- Failure window: N qualifying failures within T seconds (sliding window)
- Concurrency: asyncio.Lock per circuit to prevent thundering herd and state corruption
- Fail-open: If circuit-breaker logic itself errors, traffic passes through
- Retry interaction: Each retry attempt that qualifies counts as ONE circuit failure.
  This is deliberate: rapid retries against a failing provider should accelerate
  circuit opening to protect the system.
- Rate-limit (429) policy: A single 429 does NOT trip the circuit. Only after
  TOLLGATE_CIRCUIT_RATE_LIMIT_THRESHOLD consecutive 429s from the same provider+model
  does rate-limiting count as a circuit-tripping failure.
"""

import asyncio
import logging
import time
from collections import deque
from enum import Enum
from typing import Deque, Dict, Optional

from gateway.src.reliability.failure_classifier import FailureCategory

logger = logging.getLogger("tollgate.reliability.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# Failure categories that should count toward circuit health
CIRCUIT_TRIPPING_CATEGORIES = frozenset(
    {
        FailureCategory.TRANSIENT,  # 5xx, timeouts, connection errors
        FailureCategory.INTERNAL,  # unexpected gateway errors
    }
)

# Categories that should NEVER trip the circuit
NON_TRIPPING_CATEGORIES = frozenset(
    {
        FailureCategory.BAD_REQUEST,  # 400 — client error
        FailureCategory.NOT_FOUND,  # 404 — wrong model name
        FailureCategory.AUTHENTICATION_FAILURE,  # 401/403 — config issue
        FailureCategory.CONTENT_POLICY,  # content/safety filter
    }
)


class CircuitBreakerState:
    """Thread-safe state for a single provider+model circuit."""

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window_seconds: float = 30.0,
        open_duration_seconds: float = 30.0,
        half_open_max_calls: int = 1,
        rate_limit_threshold: int = 10,
    ):
        self.failure_threshold = failure_threshold
        self.failure_window_seconds = failure_window_seconds
        self.open_duration_seconds = open_duration_seconds
        self.half_open_max_calls = half_open_max_calls
        self.rate_limit_threshold = rate_limit_threshold

        self.state: CircuitState = CircuitState.CLOSED
        self._failure_timestamps: Deque[float] = deque()
        self._consecutive_rate_limits: int = 0
        self._opened_at: Optional[float] = None
        self._half_open_calls: int = 0
        self._last_transition_time: float = time.time()
        self._total_rejections: int = 0
        self._lock = asyncio.Lock()

    def get_failure_count(self, now: Optional[float] = None) -> int:
        """Number of qualifying failures within the sliding window at specified time."""
        current_time = now if now is not None else time.time()
        cutoff = current_time - self.failure_window_seconds
        while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
            self._failure_timestamps.popleft()
        return len(self._failure_timestamps)

    @property
    def failure_count_in_window(self) -> int:
        """Number of qualifying failures within the current sliding window."""
        return self.get_failure_count()

    def _transition_to(
        self,
        new_state: CircuitState,
        provider_key: str,
        now: Optional[float] = None,
    ) -> None:
        """Internal state transition with logging and metrics."""
        old_state = self.state
        if old_state == new_state:
            return
        current_time = now if now is not None else time.time()
        self.state = new_state
        self._last_transition_time = current_time

        if new_state == CircuitState.OPEN:
            self._opened_at = current_time
            self._half_open_calls = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_timestamps.clear()
            self._consecutive_rate_limits = 0
            self._opened_at = None

        provider, model = (
            provider_key.split(":", 1) if ":" in provider_key else (provider_key, "unknown")
        )
        try:
            from tollgate_core.observability.metrics import record_circuit_transition

            record_circuit_transition(provider, model, old_state.value, new_state.value)
        except Exception as e:
            logger.debug(f"Failed to record circuit transition metric: {e}")

        logger.info(
            f"Circuit state change: provider_key={provider_key} "
            f"from_state={old_state.value} to_state={new_state.value}"
        )

    async def before_call(self, provider_key: str, now: Optional[float] = None) -> "CircuitDecision":
        """
        Check if a call is permitted.
        Returns a CircuitDecision with allow/reject and state info.
        """
        current_time = now if now is not None else time.time()

        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return CircuitDecision(allowed=True, state=CircuitState.CLOSED)

            if self.state == CircuitState.OPEN:
                # Check if cooldown has elapsed
                if (
                    self._opened_at is not None
                    and current_time - self._opened_at >= self.open_duration_seconds
                ):
                    self._transition_to(CircuitState.HALF_OPEN, provider_key, now=current_time)
                    # Fall through to HALF_OPEN logic
                else:
                    self._total_rejections += 1
                    return CircuitDecision(
                        allowed=False,
                        state=CircuitState.OPEN,
                        reason="circuit_open",
                    )

            # HALF_OPEN: allow limited probe requests
            if self.state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return CircuitDecision(
                        allowed=True,
                        state=CircuitState.HALF_OPEN,
                        is_probe=True,
                    )
                else:
                    self._total_rejections += 1
                    return CircuitDecision(
                        allowed=False,
                        state=CircuitState.HALF_OPEN,
                        reason="half_open_probe_limit",
                    )

        return CircuitDecision(allowed=True, state=self.state)

    async def record_success(self, provider_key: str) -> None:
        """Record a successful provider call."""
        async with self._lock:
            self._consecutive_rate_limits = 0
            if self.state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.CLOSED, provider_key)
            elif self.state == CircuitState.CLOSED:
                # Reset any accumulated failures on success
                pass  # Windowed failures expire naturally

    async def record_failure(
        self,
        provider_key: str,
        failure_category: FailureCategory,
        now: Optional[float] = None,
    ) -> None:
        """
        Record a provider failure and potentially trip the circuit.

        Policy:
        - TRANSIENT and INTERNAL failures count toward circuit health
        - BAD_REQUEST, NOT_FOUND, AUTH, CONTENT_POLICY do NOT count
        - RATE_LIMITED counts only after consecutive threshold
        """
        current_time = now if now is not None else time.time()

        async with self._lock:
            # Rate-limit special handling
            if failure_category == FailureCategory.RATE_LIMITED:
                self._consecutive_rate_limits += 1
                if self._consecutive_rate_limits < self.rate_limit_threshold:
                    return  # Not enough 429s yet to consider provider unhealthy
                # Exceeded consecutive rate-limit threshold — treat as tripping
            elif failure_category in NON_TRIPPING_CATEGORIES:
                # These failures don't affect circuit health
                return
            elif failure_category not in CIRCUIT_TRIPPING_CATEGORIES:
                return
            else:
                # Reset consecutive rate-limit counter on non-rate-limit failures
                self._consecutive_rate_limits = 0

            if self.state == CircuitState.HALF_OPEN:
                # Probe failed — reopen circuit
                self._transition_to(CircuitState.OPEN, provider_key, now=current_time)
                return

            if self.state == CircuitState.CLOSED:
                self._failure_timestamps.append(current_time)
                # Prune outside window
                cutoff = current_time - self.failure_window_seconds
                while self._failure_timestamps and self._failure_timestamps[0] < cutoff:
                    self._failure_timestamps.popleft()

                if len(self._failure_timestamps) >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN, provider_key, now=current_time)

    def get_status(self) -> dict:
        """Return diagnostic information (no sensitive data)."""
        return {
            "state": self.state.value,
            "failure_count_in_window": self.failure_count_in_window,
            "failure_threshold": self.failure_threshold,
            "failure_window_seconds": self.failure_window_seconds,
            "open_duration_seconds": self.open_duration_seconds,
            "half_open_calls": self._half_open_calls,
            "half_open_max_calls": self.half_open_max_calls,
            "total_rejections": self._total_rejections,
            "last_transition_time": self._last_transition_time,
        }

    def reset(self) -> None:
        """Reset to initial state (for testing)."""
        self.state = CircuitState.CLOSED
        self._failure_timestamps.clear()
        self._consecutive_rate_limits = 0
        self._opened_at = None
        self._half_open_calls = 0
        self._total_rejections = 0
        self._last_transition_time = time.time()


class CircuitDecision:
    """Result of a circuit breaker check."""

    __slots__ = ("allowed", "state", "reason", "is_probe")

    def __init__(
        self,
        allowed: bool,
        state: CircuitState,
        reason: str = "",
        is_probe: bool = False,
    ):
        self.allowed = allowed
        self.state = state
        self.reason = reason
        self.is_probe = is_probe

    @property
    def is_open(self) -> bool:
        return not self.allowed


class CircuitBreakerException(Exception):
    """Raised when a provider call is rejected by the circuit breaker."""

    def __init__(self, provider_key: str, state: CircuitState):
        self.provider_key = provider_key
        self.state = state
        super().__init__(f"Circuit breaker OPEN for {provider_key}")


def make_provider_key(provider_name: str, model: str) -> str:
    """Create a bounded-cardinality circuit breaker key."""
    return f"{provider_name}:{model}"


class CircuitBreakerRegistry:
    """
    Manages circuit breaker instances for all provider+model pairs.

    In-memory implementation suitable for single-instance gateway.
    Limitation: Multiple gateway replicas have independent circuit state.
    """

    def __init__(
        self,
        enabled: bool = True,
        failure_threshold: int = 5,
        failure_window_seconds: float = 30.0,
        open_duration_seconds: float = 30.0,
        half_open_max_calls: int = 1,
        rate_limit_threshold: int = 10,
    ):
        self.enabled = enabled
        self.failure_threshold = failure_threshold
        self.failure_window_seconds = failure_window_seconds
        self.open_duration_seconds = open_duration_seconds
        self.half_open_max_calls = half_open_max_calls
        self.rate_limit_threshold = rate_limit_threshold
        self._circuits: Dict[str, CircuitBreakerState] = {}
        self._registry_lock = asyncio.Lock()

    def _get_or_create_circuit(self, provider_key: str) -> CircuitBreakerState:
        """Get or lazily create a circuit for a provider+model key."""
        if provider_key not in self._circuits:
            self._circuits[provider_key] = CircuitBreakerState(
                failure_threshold=self.failure_threshold,
                failure_window_seconds=self.failure_window_seconds,
                open_duration_seconds=self.open_duration_seconds,
                half_open_max_calls=self.half_open_max_calls,
                rate_limit_threshold=self.rate_limit_threshold,
            )
        return self._circuits[provider_key]

    async def before_call(
        self, provider_name: str, model: str, now: Optional[float] = None
    ) -> CircuitDecision:
        """
        Check circuit state before making a provider call.
        Fail-open: if circuit logic errors, allow the call.
        """
        if not self.enabled:
            return CircuitDecision(allowed=True, state=CircuitState.CLOSED)

        try:
            key = make_provider_key(provider_name, model)
            circuit = self._get_or_create_circuit(key)
            return await circuit.before_call(key, now=now)
        except Exception as e:
            logger.debug(f"Circuit breaker check failed (fail-open): {e}")
            return CircuitDecision(allowed=True, state=CircuitState.CLOSED)

    async def record_success(self, provider_name: str, model: str) -> None:
        """Record a successful provider call."""
        if not self.enabled:
            return
        try:
            key = make_provider_key(provider_name, model)
            circuit = self._get_or_create_circuit(key)
            await circuit.record_success(key)
        except Exception as e:
            logger.debug(f"Circuit breaker record_success failed: {e}")

    async def record_failure(
        self,
        provider_name: str,
        model: str,
        failure_category: FailureCategory,
        now: Optional[float] = None,
    ) -> None:
        """Record a provider failure."""
        if not self.enabled:
            return
        try:
            key = make_provider_key(provider_name, model)
            circuit = self._get_or_create_circuit(key)
            await circuit.record_failure(key, failure_category, now=now)
        except Exception as e:
            logger.debug(f"Circuit breaker record_failure failed: {e}")

    def is_available(
        self, provider_name: str, model: str, now: Optional[float] = None
    ) -> bool:
        """
        Synchronous availability check (for quick pre-filtering).
        Does NOT consume a half-open probe slot.
        """
        if not self.enabled:
            return True
        try:
            key = make_provider_key(provider_name, model)
            if key not in self._circuits:
                return True
            circuit = self._circuits[key]
            current_time = now if now is not None else time.time()

            if circuit.state == CircuitState.CLOSED:
                return True
            if circuit.state == CircuitState.OPEN:
                if (
                    circuit._opened_at is not None
                    and current_time - circuit._opened_at >= circuit.open_duration_seconds
                ):
                    return True  # Cooldown elapsed, will transition to HALF_OPEN
                return False
            if circuit.state == CircuitState.HALF_OPEN:
                return circuit._half_open_calls < circuit.half_open_max_calls
            return True
        except Exception:
            return True  # Fail-open

    def get_all_status(self) -> dict:
        """Return diagnostic status for all circuits."""
        return {key: circuit.get_status() for key, circuit in self._circuits.items()}

    def get_circuit_status(self, provider_name: str, model: str) -> Optional[dict]:
        """Return diagnostic status for a specific circuit."""
        key = make_provider_key(provider_name, model)
        if key in self._circuits:
            return self._circuits[key].get_status()
        return None

    def reset(self) -> None:
        """Reset all circuits (for testing)."""
        self._circuits.clear()

    def reset_circuit(self, provider_name: str, model: str) -> None:
        """Reset a specific circuit (for testing or admin)."""
        key = make_provider_key(provider_name, model)
        if key in self._circuits:
            self._circuits[key].reset()


def create_circuit_breaker_registry_from_settings() -> CircuitBreakerRegistry:
    """Create a CircuitBreakerRegistry initialized from application settings."""
    try:
        from tollgate_core.config import get_settings

        s = get_settings()
        return CircuitBreakerRegistry(
            enabled=s.circuit_breaker_enabled,
            failure_threshold=s.circuit_failure_threshold,
            failure_window_seconds=s.circuit_failure_window_seconds,
            open_duration_seconds=s.circuit_open_duration_seconds,
            half_open_max_calls=s.circuit_half_open_max_calls,
            rate_limit_threshold=s.circuit_rate_limit_threshold,
        )
    except Exception as e:
        logger.warning(
            f"Failed to load circuit breaker settings, falling back to defaults: {e}"
        )
        return CircuitBreakerRegistry()


# Default global circuit breaker registry
circuit_breaker_registry = create_circuit_breaker_registry_from_settings()
