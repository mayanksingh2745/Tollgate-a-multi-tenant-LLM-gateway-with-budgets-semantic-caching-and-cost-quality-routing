import asyncio
import random
from typing import Callable, Optional


class BackoffStrategy:
    """
    Computes exponential backoff delay with bounded jitter,
    respecting retry-after hints and test-injected sleep/clock functions.
    """

    def __init__(
        self,
        base_delay: float = 0.25,
        max_delay: float = 5.0,
        jitter: bool = True,
        sleep_func: Optional[Callable[[float], any]] = None,
        random_func: Optional[Callable[[float, float], float]] = None,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._sleep_func = sleep_func or asyncio.sleep
        self._random_func = random_func or random.uniform

    def compute_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculates the retry delay for the given attempt index (1-based: 1, 2, 3...).
        attempt=1: initial backoff delay
        """
        # Exponential formula: base_delay * 2^(attempt - 1)
        exp_delay = self.base_delay * (2 ** max(0, attempt - 1))
        bounded_delay = min(self.max_delay, exp_delay)

        if self.jitter:
            # Full/bounded jitter: random between 50% and 100% of bounded_delay, minimum 0.01s
            jittered = self._random_func(bounded_delay * 0.5, bounded_delay)
            final_delay = min(self.max_delay, max(0.01, jittered))
        else:
            final_delay = bounded_delay

        # If upstream gave Retry-After hint, respect it but bound by max_delay
        if retry_after is not None and retry_after > 0:
            final_delay = min(self.max_delay, max(final_delay, retry_after))

        return round(final_delay, 4)

    async def sleep(self, delay: float):
        """Asynchronously sleep for the computed delay."""
        res = self._sleep_func(delay)
        if asyncio.iscoroutine(res):
            await res
