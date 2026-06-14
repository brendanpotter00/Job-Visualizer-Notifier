"""Unit tests for the in-memory SlidingWindowRateLimiter.

Uses an injected fake clock so behavior is deterministic without sleeping.
"""

from api.services.rate_limit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _limiter(max_requests=3, window=60.0):
    clock = FakeClock()
    return SlidingWindowRateLimiter(max_requests, window, time_fn=clock), clock


def test_allows_up_to_the_limit():
    limiter, _ = _limiter(max_requests=3, window=60)
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None


def test_rejects_over_the_limit_with_retry_after():
    limiter, _ = _limiter(max_requests=2, window=60)
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    retry_after = limiter.check("ip")
    assert retry_after is not None
    assert retry_after > 0


def test_retry_after_counts_down_as_window_elapses():
    limiter, clock = _limiter(max_requests=1, window=60)
    assert limiter.check("ip") is None  # records hit at t=1000
    assert limiter.check("ip") == 60  # oldest expires at 1060, now 1000
    clock.advance(10)
    assert limiter.check("ip") == 50  # oldest still 1000, now 1010


def test_window_expiry_frees_the_key():
    limiter, clock = _limiter(max_requests=1, window=60)
    assert limiter.check("ip") is None
    assert limiter.check("ip") is not None  # blocked
    clock.advance(61)  # original hit has aged out of the window
    assert limiter.check("ip") is None  # allowed again


def test_distinct_keys_are_independent():
    limiter, _ = _limiter(max_requests=1, window=60)
    assert limiter.check("a") is None
    assert limiter.check("a") is not None  # a is blocked
    assert limiter.check("b") is None  # b is unaffected


def test_reset_clears_state():
    limiter, _ = _limiter(max_requests=1, window=60)
    assert limiter.check("ip") is None
    assert limiter.check("ip") is not None
    limiter.reset()
    assert limiter.check("ip") is None
