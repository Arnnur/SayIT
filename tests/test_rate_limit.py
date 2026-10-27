from app.rate_limit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_allows_up_to_limit_then_blocks():
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=FakeClock())
    assert limiter.allow("1.1.1.1")
    assert limiter.allow("1.1.1.1")
    assert not limiter.allow("1.1.1.1")


def test_window_expires():
    clock = FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
    assert limiter.allow("ip")
    assert not limiter.allow("ip")
    clock.now += 61
    assert limiter.allow("ip")


def test_keys_are_independent():
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=FakeClock())
    assert limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("a")


def test_zero_disables_limit():
    limiter = RateLimiter(max_requests=0, window_seconds=60, clock=FakeClock())
    assert all(limiter.allow("ip") for _ in range(100))
