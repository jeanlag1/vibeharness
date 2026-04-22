import pytest

from vibeharness.retry import call_with_retry, is_retryable


class FakeRateLimit(Exception):
    def __init__(self, retry_after=None):
        super().__init__("rate limit exceeded")
        self.status_code = 429
        if retry_after is not None:
            self.response = type("R", (), {"headers": {"Retry-After": str(retry_after)}})()


class Overloaded(Exception):
    def __init__(self):
        super().__init__("Overloaded")
        self.status_code = 529


class FakeBadRequest(Exception):
    def __init__(self):
        super().__init__("bad request")
        self.status_code = 400


def test_is_retryable_classifies_correctly():
    assert is_retryable(FakeRateLimit())
    assert is_retryable(Overloaded())
    assert not is_retryable(FakeBadRequest())
    assert not is_retryable(ValueError("nope"))


def test_call_with_retry_eventually_succeeds():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeRateLimit()
        return "ok"
    sleeps: list[float] = []
    out = call_with_retry(fn, sleep=sleeps.append)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_call_with_retry_honors_retry_after():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise FakeRateLimit(retry_after=2.5)
        return "ok"
    sleeps: list[float] = []
    call_with_retry(fn, sleep=sleeps.append)
    assert sleeps == [2.5]


def test_call_with_retry_gives_up_after_max():
    def fn():
        raise FakeRateLimit()
    with pytest.raises(FakeRateLimit):
        call_with_retry(fn, max_retries=2, sleep=lambda _s: None)


def test_call_with_retry_does_not_retry_non_retryable():
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        raise FakeBadRequest()
    with pytest.raises(FakeBadRequest):
        call_with_retry(fn, sleep=lambda _s: None)
    assert calls["n"] == 1


def test_on_retry_callback_invoked():
    events: list[tuple[int, float, str]] = []
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise FakeRateLimit()
        return "done"
    call_with_retry(
        fn,
        on_retry=lambda a, d, e: events.append((a, d, e.__class__.__name__)),
        sleep=lambda _s: None,
    )
    assert len(events) == 1
    assert events[0][0] == 1 and events[0][2] == "FakeRateLimit"
