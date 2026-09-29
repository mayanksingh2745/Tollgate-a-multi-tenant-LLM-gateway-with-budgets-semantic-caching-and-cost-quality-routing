import time
from typing import Dict, Optional


class ProviderHealthState:
    def __init__(self):
        self.consecutive_failures: int = 0
        self.is_healthy: bool = True
        self.unhealthy_since: Optional[float] = None
        self.last_failure_reason: str = ""


class ProviderHealthTracker:
    """
    Lightweight in-memory provider health monitor with cooldown recovery.
    Not a full distributed circuit breaker (which belongs to Phase 10).
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: Dict[str, ProviderHealthState] = {}

    def _get_state(self, provider_name: str) -> ProviderHealthState:
        if provider_name not in self._states:
            self._states[provider_name] = ProviderHealthState()
        return self._states[provider_name]

    def is_available(self, provider_name: str, now: Optional[float] = None) -> bool:
        """
        Returns True if provider is healthy or cooldown period has elapsed.
        """
        current_time = now if now is not None else time.time()
        state = self._get_state(provider_name)

        if state.is_healthy:
            return True

        # Check if cooldown has passed
        if state.unhealthy_since and (
            current_time - state.unhealthy_since >= self.cooldown_seconds
        ):
            # Probe allowed
            return True

        return False

    def record_success(self, provider_name: str):
        state = self._get_state(provider_name)
        state.is_healthy = True
        state.consecutive_failures = 0
        state.unhealthy_since = None
        state.last_failure_reason = ""

    def record_failure(self, provider_name: str, reason: str = "", now: Optional[float] = None):
        current_time = now if now is not None else time.time()
        state = self._get_state(provider_name)
        state.consecutive_failures += 1
        state.last_failure_reason = reason

        if state.consecutive_failures >= self.failure_threshold:
            state.is_healthy = False
            state.unhealthy_since = current_time

    def reset(self):
        """Reset all health states (useful for tests)."""
        self._states.clear()


# Default global health tracker
health_tracker = ProviderHealthTracker()
