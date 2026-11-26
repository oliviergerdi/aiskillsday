import httpx
import pytest

from nparity.retry import RetryExhausted, RetryPolicy, is_retryable, retry_call

POLICY = RetryPolicy()


def status_error(code):
    req = httpx.Request("POST", "https://x.test/")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, request=req))


def flaky(errors, result="ok"):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return result
    return fn, calls


def test_recovers_after_two_drops():
    sleeps = []
    fn, calls = flaky([httpx.ConnectError("reset"), httpx.RemoteProtocolError("dropped")])
    assert retry_call(fn, POLICY, sleep=sleeps.append, rand=lambda: 1.0) == "ok"
    assert calls["n"] == 3
    assert sleeps == [0.5, 1.0]


def test_backoff_capped():
    sleeps = []
    fn, _ = flaky([httpx.ReadTimeout("t")] * 3)
    retry_call(fn, RetryPolicy(attempts=4, base=5.0, cap=8.0), sleep=sleeps.append, rand=lambda: 1.0)
    assert sleeps == [5.0, 8.0, 8.0]


def test_400_not_retried():
    sleeps = []
    fn, calls = flaky([status_error(400)])
    with pytest.raises(httpx.HTTPStatusError):
        retry_call(fn, POLICY, sleep=sleeps.append)
    assert calls["n"] == 1 and sleeps == []


def test_503_exhausts():
    fn, calls = flaky([status_error(503)] * 10)
    with pytest.raises(RetryExhausted) as e:
        retry_call(fn, POLICY, sleep=lambda _: None)
    assert calls["n"] == 4 and e.value.attempts == 4


@pytest.mark.parametrize("exc,want", [
    (status_error(429), True), (status_error(529), True), (status_error(404), False),
    (httpx.ConnectTimeout("t"), True), (ValueError("x"), False),
])
def test_is_retryable(exc, want):
    assert is_retryable(exc, POLICY) is want
