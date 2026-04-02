"""Token bucket rate limiter for API calls.

Usage:
    limiter = RateLimiter(calls_per_second=5)
    limiter.acquire()  # blocks until a token is available
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(
        self,
        calls_per_second: float = 5.0,
        burst_size: int | None = None,
    ) -> None:
        self._rate = calls_per_second
        self._max_tokens = burst_size or max(int(calls_per_second * 2), 1)
        self._tokens = float(self._max_tokens)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_waits = 0

    def acquire(self, timeout: float = 30.0) -> bool:
        """Wait until a token is available. Returns False on timeout."""
        deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True

            # Wait before retry
            wait_time = min(1.0 / self._rate, deadline - time.monotonic())
            if wait_time <= 0:
                logger.warning("Rate limiter timeout after %.1fs", timeout)
                return False

            self._total_waits += 1
            time.sleep(wait_time)

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self._rate
        self._tokens = min(self._tokens + new_tokens, self._max_tokens)
        self._last_refill = now

    @property
    def total_waits(self) -> int:
        return self._total_waits


class RetryPolicy:
    """Exponential backoff retry policy."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def delay_for_attempt(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt (0-indexed)."""
        delay = self.base_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)

    def should_retry(self, attempt: int, status_code: int | None = None) -> bool:
        """Determine if we should retry based on attempt count and status code."""
        if attempt >= self.max_retries:
            return False
        # Don't retry client errors (except 429 rate limit)
        return not (status_code is not None and 400 <= status_code < 500 and status_code != 429)
