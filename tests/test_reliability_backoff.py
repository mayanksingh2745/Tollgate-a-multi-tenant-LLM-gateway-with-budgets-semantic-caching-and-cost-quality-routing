from gateway.src.reliability.backoff import BackoffStrategy


def test_exponential_backoff_progression():
    # Without jitter, delays must exactly double: base_delay * 2^(attempt - 1)
    strategy = BackoffStrategy(base_delay=0.25, max_delay=5.0, jitter=False)

    d1 = strategy.compute_delay(1)  # 0.25 * 1 = 0.25
    d2 = strategy.compute_delay(2)  # 0.25 * 2 = 0.50
    d3 = strategy.compute_delay(3)  # 0.25 * 4 = 1.00
    d4 = strategy.compute_delay(4)  # 0.25 * 8 = 2.00
    d5 = strategy.compute_delay(5)  # 0.25 * 16 = 4.00
    d6 = strategy.compute_delay(6)  # 0.25 * 32 = 8.00 -> capped at 5.00

    assert d1 == 0.25
    assert d2 == 0.50
    assert d3 == 1.00
    assert d4 == 2.00
    assert d5 == 4.00
    assert d6 == 5.00
    assert d1 < d2 < d3 < d4 < d5 <= d6


def test_backoff_max_delay_cap():
    strategy = BackoffStrategy(base_delay=1.0, max_delay=2.5, jitter=False)
    for attempt in range(1, 10):
        delay = strategy.compute_delay(attempt)
        assert delay <= 2.5


def test_backoff_with_bounded_jitter():
    # Injected deterministic random source
    strategy = BackoffStrategy(
        base_delay=0.5,
        max_delay=5.0,
        jitter=True,
        random_func=lambda low, high: (low + high) / 2,  # Midpoint
    )

    d1 = strategy.compute_delay(1)
    d2 = strategy.compute_delay(2)
    d3 = strategy.compute_delay(3)

    assert d1 < d2 < d3
    assert d3 <= 5.0


def test_retry_after_respected_within_bounds():
    strategy = BackoffStrategy(base_delay=0.1, max_delay=3.0, jitter=False)

    # Provider says Retry-After: 1.5s -> should use 1.5s
    d = strategy.compute_delay(1, retry_after=1.5)
    assert d == 1.5

    # Provider says Retry-After: 10s -> must be capped by max_delay=3.0s
    d_capped = strategy.compute_delay(1, retry_after=10.0)
    assert d_capped == 3.0
