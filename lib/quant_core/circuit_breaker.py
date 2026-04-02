"""Circuit breaker: emergency halt mechanism for all services.

The circuit breaker is a Redis key that, when set, causes all services to
stop generating signals, stop sending orders, and optionally flatten all
positions. Every service checks this key in its consume loop.

Usage:
    from quant_core.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(redis_client, run_id="live")
    if cb.is_tripped():
        # Stop processing
        ...
    cb.trip(reason="manual kill switch")
    cb.reset()
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as sync_redis

from quant_core.redis_utils import Keys

logger = logging.getLogger(__name__)

# How often (seconds) each service re-checks the breaker from Redis.
# Lower = faster response but more Redis load. 0.5s is a good default.
CHECK_INTERVAL_S = 0.5


class CircuitBreaker:
    """Redis-backed circuit breaker checked by all trading services."""

    def __init__(self, r: sync_redis.Redis, run_id: str = "live") -> None:
        self._redis = r
        self._key = Keys.circuit_breaker(run_id)
        self._run_id = run_id
        # Local cache to avoid hitting Redis on every single message
        self._cached_state: bool = False
        self._last_check: float = 0.0

    def is_tripped(self) -> bool:
        """Check if the circuit breaker is currently active.

        Uses a local cache with CHECK_INTERVAL_S TTL to reduce Redis load.
        """
        now = time.monotonic()
        if now - self._last_check < CHECK_INTERVAL_S:
            return self._cached_state

        try:
            val = self._redis.get(self._key)
            self._cached_state = val is not None
        except Exception:
            # If Redis is down, assume tripped (fail safe)
            logger.error("Cannot reach Redis for circuit breaker check — failing safe")
            self._cached_state = True

        self._last_check = now
        return self._cached_state

    def trip(self, reason: str = "manual", triggered_by: str = "unknown") -> None:
        """Activate the circuit breaker. All services will stop trading."""
        payload = json.dumps(
            {
                "tripped": True,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": time.time(),
            }
        )
        self._redis.set(self._key, payload)
        self._cached_state = True
        self._last_check = time.monotonic()
        logger.critical(
            "CIRCUIT BREAKER TRIPPED — reason=%s, triggered_by=%s",
            reason,
            triggered_by,
        )

    def reset(self, reset_by: str = "unknown") -> None:
        """Clear the circuit breaker. Services will resume trading."""
        self._redis.delete(self._key)
        self._cached_state = False
        self._last_check = time.monotonic()
        logger.warning("Circuit breaker RESET by %s", reset_by)

    def status(self) -> dict:
        """Return the current circuit breaker state as a dict."""
        val = self._redis.get(self._key)
        if val is None:
            return {"tripped": False, "run_id": self._run_id}
        try:
            data = json.loads(val)
            data["run_id"] = self._run_id
            return data
        except json.JSONDecodeError, TypeError:
            return {"tripped": True, "run_id": self._run_id, "raw": str(val)}
