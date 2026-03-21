"""Redis connection helpers and shared key schema.

All keys follow the pattern: {namespace}:{run_id}:{entity}
This allows backtest isolation by run_id.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
import redis as sync_redis

from quant_core.config import RedisConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key schema constants
# ---------------------------------------------------------------------------

class Keys:
    """Centralized Redis key templates."""

    # Order book
    @staticmethod
    def book_bids(symbol: str) -> str:
        return f"book:{symbol}:bids"

    @staticmethod
    def book_asks(symbol: str) -> str:
        return f"book:{symbol}:asks"

    @staticmethod
    def book_mid(symbol: str) -> str:
        return f"book:{symbol}:mid_price"

    @staticmethod
    def book_spread(symbol: str) -> str:
        return f"book:{symbol}:spread"

    @staticmethod
    def book_last_update(symbol: str) -> str:
        return f"book:{symbol}:last_update"

    # Features
    @staticmethod
    def feature(symbol: str, name: str) -> str:
        return f"features:{symbol}:{name}"

    # Positions / Portfolio
    @staticmethod
    def position(run_id: str, symbol: str) -> str:
        return f"positions:{run_id}:{symbol}"

    @staticmethod
    def portfolio(run_id: str) -> str:
        return f"portfolio:{run_id}"

    # Risk
    @staticmethod
    def risk_limits(run_id: str) -> str:
        return f"risk:limits:{run_id}"

    @staticmethod
    def circuit_breaker(run_id: str) -> str:
        return f"risk:circuit_breaker:{run_id}"

    @staticmethod
    def order_timestamps(run_id: str, symbol: str) -> str:
        return f"risk:order_timestamps:{run_id}:{symbol}"

    # Heartbeat
    @staticmethod
    def heartbeat(service: str) -> str:
        return f"heartbeat:{service}"


# ---------------------------------------------------------------------------
# Connection factories
# ---------------------------------------------------------------------------

def create_async_redis(config: RedisConfig) -> aioredis.Redis:
    """Create an async Redis connection."""
    return aioredis.from_url(
        config.url,
        decode_responses=True,
        max_connections=20,
    )


def create_sync_redis(config: RedisConfig) -> sync_redis.Redis:
    """Create a synchronous Redis connection."""
    return sync_redis.from_url(
        config.url,
        decode_responses=True,
        max_connections=10,
    )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

async def async_hset_dict(
    r: aioredis.Redis, key: str, data: dict[str, Any]
) -> None:
    """Write a dict as a Redis hash, JSON-encoding non-string values."""
    flat = {}
    for k, v in data.items():
        if isinstance(v, (dict, list)):
            flat[k] = json.dumps(v)
        else:
            flat[k] = str(v)
    await r.hset(key, mapping=flat)


async def async_hget_dict(r: aioredis.Redis, key: str) -> dict[str, str]:
    """Read all fields from a Redis hash."""
    return await r.hgetall(key)
