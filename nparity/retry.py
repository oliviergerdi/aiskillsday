"""Per-call retry: exponential backoff with full jitter. Used by replay and the LLM backend."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import httpx

T = TypeVar("T")

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base: float = 0.5
    cap: float = 8.0
    statuses: frozenset[int] = field(default=RETRY_STATUSES)


class RetryExhausted(Exception):
    def __init__(self, attempts: int, last: Exception):
        super().__init__(f"{type(last).__name__}: {last} (after {attempts} attempts)")
        self.attempts = attempts
        self.last = last


def is_retryable(exc: Exception, policy: RetryPolicy) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in policy.statuses
    return isinstance(exc, httpx.TransportError)   # includes timeouts, connect errors, dropped connections


def retry_call(fn: Callable[[], T], policy: RetryPolicy, *, sleep: Callable[[float], None] = time.sleep,
               rand: Callable[[], float] = random.random,
               on_retry: Callable[[int, Exception, float], None] | None = None) -> T:
    for attempt in range(policy.attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc, policy):
                raise
            if attempt == policy.attempts - 1:
                raise RetryExhausted(policy.attempts, exc) from exc
            delay = rand() * min(policy.cap, policy.base * 2 ** attempt)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            sleep(delay)
    raise AssertionError("unreachable")
