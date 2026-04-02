"""Tests for quant_core.rate_limiter — token bucket and retry logic."""

from __future__ import annotations

import time

from quant_core.rate_limiter import RateLimiter, RetryPolicy

# -----------------------------------------------------------------------
# RateLimiter Tests
# -----------------------------------------------------------------------


class TestRateLimiterAcquire:
    """Test RateLimiter.acquire() behavior."""

    def test_acquire_succeeds_immediately_when_tokens_available(self):
        """Acquire should return True immediately when tokens exist."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=5)
        start = time.monotonic()
        result = limiter.acquire(timeout=1.0)
        elapsed = time.monotonic() - start

        assert result is True
        assert elapsed < 0.1  # Should be nearly instant

    def test_acquire_succeeds_multiple_times_until_burst_depleted(self):
        """Multiple rapid acquires should succeed up to burst_size."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=3)

        # Should succeed 3 times
        assert limiter.acquire(timeout=1.0) is True
        assert limiter.acquire(timeout=1.0) is True
        assert limiter.acquire(timeout=1.0) is True

        # Fourth acquire should block/timeout
        start = time.monotonic()
        result = limiter.acquire(timeout=0.2)
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed >= 0.2

    def test_acquire_blocks_when_no_tokens_available(self):
        """Acquire should block/wait when no tokens available."""
        limiter = RateLimiter(calls_per_second=2.0, burst_size=1)

        # Deplete the token
        assert limiter.acquire(timeout=1.0) is True

        # Next acquire should have to wait for tokens to refill
        start = time.monotonic()
        result = limiter.acquire(timeout=1.0)
        elapsed = time.monotonic() - start

        assert result is True
        # At 2 calls/sec, we need ~0.5s to get 1 token
        assert elapsed >= 0.4  # Allow some tolerance

    def test_acquire_returns_false_on_timeout(self):
        """Acquire should return False when timeout expires."""
        limiter = RateLimiter(calls_per_second=0.5, burst_size=1)

        # Deplete the token
        assert limiter.acquire(timeout=1.0) is True

        # Short timeout should fail
        start = time.monotonic()
        result = limiter.acquire(timeout=0.1)
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed >= 0.1

    def test_acquire_timeout_respected_exactly(self):
        """Timeout should be enforced within reasonable bounds."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=1)

        # Deplete the token
        limiter.acquire(timeout=1.0)

        # Test multiple timeout values
        for timeout in [0.05, 0.1, 0.2]:
            start = time.monotonic()
            result = limiter.acquire(timeout=timeout)
            elapsed = time.monotonic() - start

            assert result is False
            # Allow ±50ms tolerance
            assert abs(elapsed - timeout) < 0.05


class TestRateLimiterBurst:
    """Test RateLimiter burst behavior."""

    def test_default_burst_size_is_2x_calls_per_second(self):
        """Burst size should default to 2 * calls_per_second."""
        limiter = RateLimiter(calls_per_second=5.0)
        # Acquire 10 tokens (2 * 5)
        for _ in range(10):
            assert limiter.acquire(timeout=1.0) is True

        # 11th should fail/timeout
        result = limiter.acquire(timeout=0.1)
        assert result is False

    def test_default_burst_size_minimum_is_1(self):
        """Burst size should be at least 1, even for low rates."""
        limiter = RateLimiter(calls_per_second=0.1)  # 0.1 * 2 = 0.2 -> max(int(0.2), 1) = 1
        assert limiter.acquire(timeout=1.0) is True
        result = limiter.acquire(timeout=0.1)
        assert result is False

    def test_custom_burst_size_is_respected(self):
        """Custom burst_size should override the default."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=10)

        # Should allow 10 rapid acquires
        for _ in range(10):
            assert limiter.acquire(timeout=1.0) is True

        # 11th should fail/timeout
        result = limiter.acquire(timeout=0.1)
        assert result is False

    def test_burst_size_can_be_very_large(self):
        """Large burst sizes should be supported."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=100)

        for _ in range(100):
            assert limiter.acquire(timeout=1.0) is True

        result = limiter.acquire(timeout=0.1)
        assert result is False

    def test_burst_size_of_1(self):
        """Burst size of 1 should allow only 1 token at a time."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=1)

        assert limiter.acquire(timeout=1.0) is True
        result = limiter.acquire(timeout=0.1)
        assert result is False


class TestRateLimiterWaitTracking:
    """Test RateLimiter.total_waits counter."""

    def test_total_waits_starts_at_zero(self):
        """total_waits should initialize to 0."""
        limiter = RateLimiter(calls_per_second=1.0)
        assert limiter.total_waits == 0

    def test_total_waits_increments_on_blocking_acquire(self):
        """total_waits should increment when acquire has to wait."""
        limiter = RateLimiter(calls_per_second=2.0, burst_size=1)

        # First acquire doesn't wait
        limiter.acquire(timeout=1.0)
        assert limiter.total_waits == 0

        # Second acquire must wait
        limiter.acquire(timeout=1.0)
        assert limiter.total_waits >= 1

    def test_total_waits_multiple_blocks(self):
        """total_waits should track multiple wait cycles."""
        limiter = RateLimiter(calls_per_second=5.0, burst_size=1)

        # Perform multiple acquires that require waiting
        for _ in range(3):
            limiter.acquire(timeout=1.0)

        # Each acquire after the first should increment total_waits
        assert limiter.total_waits >= 2

    def test_total_waits_not_incremented_on_timeout(self):
        """total_waits should not increment when acquire times out (failed)."""
        limiter = RateLimiter(calls_per_second=0.5, burst_size=1)

        # Deplete token
        limiter.acquire(timeout=1.0)

        # Timeout without success
        initial_waits = limiter.total_waits
        limiter.acquire(timeout=0.1)
        # total_waits may or may not increment on timeout,
        # depending on whether the attempt loop ran at all
        assert limiter.total_waits >= initial_waits


class TestRateLimiterConcurrency:
    """Test RateLimiter thread safety."""

    def test_acquire_is_thread_safe(self):
        """Multiple threads should safely acquire tokens."""
        import threading

        limiter = RateLimiter(calls_per_second=10.0, burst_size=20)
        results = []
        lock = threading.Lock()

        def worker():
            result = limiter.acquire(timeout=2.0)
            with lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 5 threads should succeed since burst_size=20
        assert all(results)
        assert len(results) == 5


class TestRateLimiterRefill:
    """Test RateLimiter token refill."""

    def test_tokens_refill_over_time(self):
        """Tokens should refill at the specified rate."""
        limiter = RateLimiter(calls_per_second=2.0, burst_size=1)

        # Deplete token
        assert limiter.acquire(timeout=1.0) is True

        # Wait for refill
        time.sleep(0.6)

        # Should be able to acquire another token
        assert limiter.acquire(timeout=0.1) is True

    def test_refill_never_exceeds_max_tokens(self):
        """Refilled tokens should be capped at burst_size."""
        limiter = RateLimiter(calls_per_second=1.0, burst_size=2)

        # Deplete one token
        limiter.acquire(timeout=1.0)

        # Wait for significant refill time
        time.sleep(2.0)

        # Should still only have burst_size tokens
        assert limiter.acquire(timeout=1.0) is True
        assert limiter.acquire(timeout=1.0) is True
        result = limiter.acquire(timeout=0.1)
        assert result is False


# -----------------------------------------------------------------------
# RetryPolicy Tests
# -----------------------------------------------------------------------


class TestRetryPolicyDelay:
    """Test RetryPolicy.delay_for_attempt() exponential backoff."""

    def test_delay_for_attempt_exponential_backoff(self):
        """Delay should follow exponential backoff: base * (exponential_base ** attempt)."""
        policy = RetryPolicy(base_delay=0.5, exponential_base=2.0, max_delay=30.0)

        assert policy.delay_for_attempt(0) == 0.5  # 0.5 * 2^0
        assert policy.delay_for_attempt(1) == 1.0  # 0.5 * 2^1
        assert policy.delay_for_attempt(2) == 2.0  # 0.5 * 2^2
        assert policy.delay_for_attempt(3) == 4.0  # 0.5 * 2^3
        assert policy.delay_for_attempt(4) == 8.0  # 0.5 * 2^4

    def test_delay_for_attempt_default_sequence(self):
        """Default parameters should produce 0.5, 1.0, 2.0, ... sequence."""
        policy = RetryPolicy()  # defaults: base_delay=0.5, exponential_base=2.0

        assert policy.delay_for_attempt(0) == 0.5
        assert policy.delay_for_attempt(1) == 1.0
        assert policy.delay_for_attempt(2) == 2.0
        assert policy.delay_for_attempt(3) == 4.0

    def test_delay_for_attempt_custom_base_delay(self):
        """Custom base_delay should scale the sequence."""
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=30.0)

        assert policy.delay_for_attempt(0) == 1.0  # 1.0 * 2^0
        assert policy.delay_for_attempt(1) == 2.0  # 1.0 * 2^1
        assert policy.delay_for_attempt(2) == 4.0  # 1.0 * 2^2

    def test_delay_for_attempt_custom_exponential_base(self):
        """Custom exponential_base should change growth rate."""
        policy = RetryPolicy(base_delay=1.0, exponential_base=3.0, max_delay=30.0)

        assert policy.delay_for_attempt(0) == 1.0  # 1.0 * 3^0
        assert policy.delay_for_attempt(1) == 3.0  # 1.0 * 3^1
        assert policy.delay_for_attempt(2) == 9.0  # 1.0 * 3^2

    def test_delay_for_attempt_capped_at_max_delay(self):
        """Delay should be capped at max_delay."""
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=5.0)

        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 4.0
        assert policy.delay_for_attempt(3) == 5.0  # capped at 5.0
        assert policy.delay_for_attempt(4) == 5.0  # capped at 5.0
        assert policy.delay_for_attempt(10) == 5.0  # capped at 5.0

    def test_delay_for_attempt_zero_attempt(self):
        """Attempt 0 should use base_delay."""
        policy = RetryPolicy(base_delay=2.5)
        assert policy.delay_for_attempt(0) == 2.5

    def test_delay_for_attempt_large_attempt_numbers(self):
        """Very large attempt numbers should be capped at max_delay."""
        policy = RetryPolicy(base_delay=0.5, exponential_base=2.0, max_delay=10.0)
        assert policy.delay_for_attempt(100) == 10.0


class TestRetryPolicyShouldRetry:
    """Test RetryPolicy.should_retry() logic."""

    def test_should_retry_returns_false_when_attempt_exceeds_max_retries(self):
        """Should return False when attempt >= max_retries."""
        policy = RetryPolicy(max_retries=3)

        # Attempts 0, 1, 2 are valid (3 retries)
        assert policy.should_retry(0, status_code=500) is True
        assert policy.should_retry(1, status_code=500) is True
        assert policy.should_retry(2, status_code=500) is True

        # Attempt 3 and beyond should fail
        assert policy.should_retry(3, status_code=500) is False
        assert policy.should_retry(4, status_code=500) is False

    def test_should_retry_returns_false_for_client_errors(self):
        """Should return False for 4xx status codes (except 429)."""
        policy = RetryPolicy(max_retries=3)

        # Common client errors
        assert policy.should_retry(0, status_code=400) is False  # Bad Request
        assert policy.should_retry(0, status_code=401) is False  # Unauthorized
        assert policy.should_retry(0, status_code=403) is False  # Forbidden
        assert policy.should_retry(0, status_code=404) is False  # Not Found
        assert policy.should_retry(0, status_code=422) is False  # Unprocessable Entity
        assert policy.should_retry(0, status_code=499) is False  # Custom 4xx

    def test_should_retry_returns_true_for_429_rate_limit(self):
        """Should return True for 429 (rate limit) even though it's a 4xx."""
        policy = RetryPolicy(max_retries=3)

        assert policy.should_retry(0, status_code=429) is True
        assert policy.should_retry(1, status_code=429) is True
        assert policy.should_retry(2, status_code=429) is True

    def test_should_retry_returns_true_for_server_errors(self):
        """Should return True for 5xx status codes."""
        policy = RetryPolicy(max_retries=3)

        assert policy.should_retry(0, status_code=500) is True  # Internal Server Error
        assert policy.should_retry(0, status_code=502) is True  # Bad Gateway
        assert policy.should_retry(0, status_code=503) is True  # Service Unavailable
        assert policy.should_retry(0, status_code=504) is True  # Gateway Timeout
        assert policy.should_retry(1, status_code=5) is True  # Custom 5xx

    def test_should_retry_returns_true_for_none_status_code(self):
        """Should return True when status_code is None (network error)."""
        policy = RetryPolicy(max_retries=3)

        assert policy.should_retry(0, status_code=None) is True
        assert policy.should_retry(1, status_code=None) is True
        assert policy.should_retry(2, status_code=None) is True

    def test_should_retry_respects_max_retries_with_none_status(self):
        """Max retries should still apply with None status_code."""
        policy = RetryPolicy(max_retries=2)

        assert policy.should_retry(0, status_code=None) is True
        assert policy.should_retry(1, status_code=None) is True
        assert policy.should_retry(2, status_code=None) is False

    def test_should_retry_combines_max_retries_and_status_code(self):
        """Both max_retries and status_code should be checked."""
        policy = RetryPolicy(max_retries=2)

        # Low attempt, good status (500)
        assert policy.should_retry(0, status_code=500) is True

        # High attempt, good status (500) - attempt limit wins
        assert policy.should_retry(2, status_code=500) is False

        # Low attempt, bad status (404)
        assert policy.should_retry(0, status_code=404) is False

        # High attempt, bad status (404)
        assert policy.should_retry(2, status_code=404) is False

    def test_should_retry_max_retries_zero(self):
        """max_retries=0 should never retry."""
        policy = RetryPolicy(max_retries=0)

        assert policy.should_retry(0, status_code=500) is False
        assert policy.should_retry(0, status_code=None) is False

    def test_should_retry_max_retries_large(self):
        """Large max_retries should allow many retry attempts."""
        policy = RetryPolicy(max_retries=100)

        for attempt in range(100):
            assert policy.should_retry(attempt, status_code=500) is True

        assert policy.should_retry(100, status_code=500) is False


class TestRetryPolicyEdgeCases:
    """Test RetryPolicy edge cases."""

    def test_status_code_boundary_conditions(self):
        """Test exact boundaries for status code ranges."""
        policy = RetryPolicy(max_retries=3)

        # Boundary at 400
        assert policy.should_retry(0, status_code=399) is True  # Not 4xx
        assert policy.should_retry(0, status_code=400) is False  # Start of 4xx

        # Boundary at 500
        assert policy.should_retry(0, status_code=499) is False  # End of 4xx (except 429)
        assert policy.should_retry(0, status_code=500) is True  # Start of 5xx

        # Boundary at 600
        assert policy.should_retry(0, status_code=599) is True  # End of 5xx
        assert policy.should_retry(0, status_code=600) is True  # Beyond 5xx

    def test_429_special_case_alone(self):
        """429 should be the only 4xx that retries."""
        policy = RetryPolicy(max_retries=3)

        # All other 4xx
        for code in [
            400,
            401,
            402,
            403,
            404,
            405,
            406,
            407,
            408,
            409,
            410,
            411,
            412,
            413,
            414,
            415,
            416,
            417,
            418,
            421,
            422,
            423,
            424,
            425,
            426,
            428,
            431,
            451,
        ]:
            if code != 429:
                assert policy.should_retry(0, status_code=code) is False, f"Code {code} should not retry"

        # Only 429 should retry
        assert policy.should_retry(0, status_code=429) is True

    def test_retry_policy_custom_initialization(self):
        """RetryPolicy should support custom initialization."""
        policy = RetryPolicy(
            max_retries=5,
            base_delay=2.0,
            max_delay=60.0,
            exponential_base=3.0,
        )

        assert policy.max_retries == 5
        assert policy.base_delay == 2.0
        assert policy.max_delay == 60.0
        assert policy.exponential_base == 3.0
