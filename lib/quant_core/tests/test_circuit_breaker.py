"""Tests for quant_core.circuit_breaker — Redis-backed circuit breaker."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from quant_core.circuit_breaker import CHECK_INTERVAL_S, CircuitBreaker
from quant_core.redis_utils import Keys


class TestCircuitBreakerIsTripped:
    """Tests for CircuitBreaker.is_tripped() method."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def circuit_breaker(self, mock_redis):
        """Create a CircuitBreaker instance with mocked Redis."""
        return CircuitBreaker(mock_redis, run_id="live")

    def test_is_tripped_returns_false_when_redis_key_is_none(self, circuit_breaker, mock_redis):
        """is_tripped() returns False when Redis key doesn't exist."""
        mock_redis.get.return_value = None

        result = circuit_breaker.is_tripped()

        assert result is False
        mock_redis.get.assert_called_once()

    def test_is_tripped_returns_true_when_redis_key_is_set(self, circuit_breaker, mock_redis):
        """is_tripped() returns True when Redis key exists."""
        payload = json.dumps(
            {
                "tripped": True,
                "reason": "test",
                "triggered_by": "test_user",
                "timestamp": time.time(),
            }
        )
        mock_redis.get.return_value = payload.encode()

        result = circuit_breaker.is_tripped()

        assert result is True
        mock_redis.get.assert_called_once()

    def test_is_tripped_caches_result_and_avoids_redis_within_ttl(self, circuit_breaker, mock_redis):
        """is_tripped() caches result and doesn't hit Redis within CHECK_INTERVAL_S."""
        mock_redis.get.return_value = None

        # First call hits Redis
        result1 = circuit_breaker.is_tripped()
        assert result1 is False
        assert mock_redis.get.call_count == 1

        # Second call (within TTL) uses cache
        result2 = circuit_breaker.is_tripped()
        assert result2 is False
        assert mock_redis.get.call_count == 1  # Still 1, not incremented

        # After TTL expires, Redis is hit again
        with patch("time.monotonic") as mock_monotonic:
            # Set monotonic time to be past the TTL
            mock_monotonic.return_value = circuit_breaker._last_check + CHECK_INTERVAL_S + 0.1
            result3 = circuit_breaker.is_tripped()
            assert result3 is False
            assert mock_redis.get.call_count == 2  # Incremented

    def test_is_tripped_returns_true_when_redis_raises_exception(self, circuit_breaker, mock_redis):
        """is_tripped() returns True (fail-safe) when Redis is unreachable."""
        mock_redis.get.side_effect = Exception("Redis connection failed")

        result = circuit_breaker.is_tripped()

        # Fail-safe: returns True when Redis is down
        assert result is True

    def test_is_tripped_caches_fail_safe_state(self, circuit_breaker, mock_redis):
        """is_tripped() caches the fail-safe state and doesn't retry Redis within TTL."""
        mock_redis.get.side_effect = Exception("Redis connection failed")

        # First call fails, cached as True
        result1 = circuit_breaker.is_tripped()
        assert result1 is True
        assert mock_redis.get.call_count == 1

        # Second call (within TTL) uses cache without hitting Redis again
        result2 = circuit_breaker.is_tripped()
        assert result2 is True
        assert mock_redis.get.call_count == 1  # Still 1, not incremented


class TestCircuitBreakerTrip:
    """Tests for CircuitBreaker.trip() method."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def circuit_breaker(self, mock_redis):
        """Create a CircuitBreaker instance with mocked Redis."""
        return CircuitBreaker(mock_redis, run_id="live")

    def test_trip_sets_redis_key_with_json_payload(self, circuit_breaker, mock_redis):
        """trip() sets the Redis key with proper JSON payload."""
        with patch("time.time") as mock_time:
            mock_time.return_value = 1234567890.0

            circuit_breaker.trip(reason="manual kill", triggered_by="operator")

            mock_redis.set.assert_called_once()
            args, _kwargs = mock_redis.set.call_args

            # Check the key
            key = args[0]
            assert key == Keys.circuit_breaker("live")

            # Check the payload
            payload = json.loads(args[1])
            assert payload["tripped"] is True
            assert payload["reason"] == "manual kill"
            assert payload["triggered_by"] == "operator"
            assert payload["timestamp"] == 1234567890.0

    def test_trip_updates_local_cache_immediately(self, circuit_breaker, mock_redis):
        """trip() updates the local cache immediately."""
        # Cache should be False initially
        circuit_breaker._cached_state = False

        circuit_breaker.trip(reason="test", triggered_by="test_user")

        # Cache should be True after trip
        assert circuit_breaker._cached_state is True

    def test_trip_updates_last_check_timestamp(self, circuit_breaker, mock_redis):
        """trip() updates the _last_check timestamp to prevent immediate cache expiry."""
        original_last_check = circuit_breaker._last_check

        with patch("time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = original_last_check + 1.0

            circuit_breaker.trip(reason="test", triggered_by="test_user")

            # _last_check should be updated to current time
            assert circuit_breaker._last_check == original_last_check + 1.0

    def test_trip_with_default_parameters(self, circuit_breaker, mock_redis):
        """trip() uses sensible defaults for reason and triggered_by."""
        circuit_breaker.trip()

        mock_redis.set.assert_called_once()
        args = mock_redis.set.call_args[0]
        payload = json.loads(args[1])

        assert payload["reason"] == "manual"
        assert payload["triggered_by"] == "unknown"


class TestCircuitBreakerReset:
    """Tests for CircuitBreaker.reset() method."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def circuit_breaker(self, mock_redis):
        """Create a CircuitBreaker instance with mocked Redis."""
        return CircuitBreaker(mock_redis, run_id="live")

    def test_reset_deletes_redis_key(self, circuit_breaker, mock_redis):
        """reset() deletes the Redis key."""
        circuit_breaker.reset(reset_by="operator")

        mock_redis.delete.assert_called_once_with(Keys.circuit_breaker("live"))

    def test_reset_updates_local_cache_immediately(self, circuit_breaker, mock_redis):
        """reset() updates the local cache immediately."""
        # Cache should be True before reset
        circuit_breaker._cached_state = True

        circuit_breaker.reset(reset_by="operator")

        # Cache should be False after reset
        assert circuit_breaker._cached_state is False

    def test_reset_updates_last_check_timestamp(self, circuit_breaker, mock_redis):
        """reset() updates the _last_check timestamp."""
        original_last_check = circuit_breaker._last_check

        with patch("time.monotonic") as mock_monotonic:
            mock_monotonic.return_value = original_last_check + 1.0

            circuit_breaker.reset(reset_by="operator")

            # _last_check should be updated
            assert circuit_breaker._last_check == original_last_check + 1.0

    def test_reset_with_default_reset_by(self, circuit_breaker, mock_redis):
        """reset() uses 'unknown' as default for reset_by."""
        # Should not raise any exception
        circuit_breaker.reset()

        mock_redis.delete.assert_called_once()


class TestCircuitBreakerStatus:
    """Tests for CircuitBreaker.status() method."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def circuit_breaker(self, mock_redis):
        """Create a CircuitBreaker instance with mocked Redis."""
        return CircuitBreaker(mock_redis, run_id="live")

    def test_status_returns_not_tripped_when_key_does_not_exist(self, circuit_breaker, mock_redis):
        """status() returns {"tripped": False, "run_id": ...} when key doesn't exist."""
        mock_redis.get.return_value = None

        status = circuit_breaker.status()

        assert status == {"tripped": False, "run_id": "live"}

    def test_status_returns_parsed_json_with_run_id_added(self, circuit_breaker, mock_redis):
        """status() returns parsed JSON from Redis with run_id added."""
        payload = json.dumps(
            {
                "tripped": True,
                "reason": "emergency",
                "triggered_by": "risk_manager",
                "timestamp": 1234567890.0,
            }
        )
        mock_redis.get.return_value = payload.encode()

        status = circuit_breaker.status()

        assert status["tripped"] is True
        assert status["reason"] == "emergency"
        assert status["triggered_by"] == "risk_manager"
        assert status["timestamp"] == 1234567890.0
        assert status["run_id"] == "live"

    def test_status_handles_invalid_json_gracefully(self, circuit_breaker, mock_redis):
        """status() handles invalid JSON in Redis gracefully."""
        mock_redis.get.return_value = b"invalid json {{"

        status = circuit_breaker.status()

        assert status["tripped"] is True
        assert status["run_id"] == "live"
        assert "raw" in status
        assert status["raw"] == "b'invalid json {{'"

    def test_status_handles_non_string_json_gracefully(self, circuit_breaker, mock_redis):
        """status() handles non-string/non-dict JSON gracefully."""
        # json.loads() can succeed but return non-dict
        mock_redis.get.return_value = b"123"

        status = circuit_breaker.status()

        # Should handle TypeError gracefully
        assert status["tripped"] is True
        assert status["run_id"] == "live"
        assert "raw" in status

    def test_status_preserves_all_json_fields(self, circuit_breaker, mock_redis):
        """status() preserves all JSON fields from Redis."""
        payload = json.dumps(
            {
                "tripped": True,
                "reason": "market halt",
                "triggered_by": "compliance",
                "timestamp": 1609459200.0,
                "custom_field": "custom_value",
            }
        )
        mock_redis.get.return_value = payload.encode()

        status = circuit_breaker.status()

        assert status["custom_field"] == "custom_value"
        assert status["run_id"] == "live"


class TestCircuitBreakerIntegration:
    """Integration tests for CircuitBreaker with multiple operations."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    @pytest.fixture
    def circuit_breaker(self, mock_redis):
        """Create a CircuitBreaker instance with mocked Redis."""
        return CircuitBreaker(mock_redis, run_id="backtest-123")

    def test_trip_and_reset_cycle(self, circuit_breaker, mock_redis):
        """Test complete trip -> is_tripped -> reset -> is_tripped cycle."""
        # Initial state: not tripped
        mock_redis.get.return_value = None
        assert circuit_breaker.is_tripped() is False

        # Trip the breaker
        mock_redis.get.return_value = None  # Reset for trip
        circuit_breaker.trip(reason="test", triggered_by="test")
        assert circuit_breaker.is_tripped() is True

        # Reset the breaker
        mock_redis.get.return_value = None
        circuit_breaker.reset(reset_by="test")
        assert circuit_breaker.is_tripped() is False

    def test_different_run_ids_use_different_keys(self, mock_redis):
        """Different CircuitBreaker instances with different run_ids use different Redis keys."""
        cb_live = CircuitBreaker(mock_redis, run_id="live")
        cb_backtest = CircuitBreaker(mock_redis, run_id="backtest-456")

        cb_live.trip(reason="test", triggered_by="test")
        cb_backtest.trip(reason="test", triggered_by="test")

        # Verify different keys were used
        calls = mock_redis.set.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == Keys.circuit_breaker("live")
        assert calls[1][0][0] == Keys.circuit_breaker("backtest-456")

    def test_status_after_trip(self, circuit_breaker, mock_redis):
        """Test that status() reflects tripped state after trip()."""
        payload = json.dumps(
            {
                "tripped": True,
                "reason": "market halt",
                "triggered_by": "compliance",
                "timestamp": 1609459200.0,
            }
        )
        mock_redis.get.return_value = payload.encode()

        # After trip, status should show tripped state
        status = circuit_breaker.status()
        assert status["tripped"] is True
        assert status["reason"] == "market halt"
        assert status["run_id"] == "backtest-123"
