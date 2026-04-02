"""Redis-backed portfolio state for the risk gateway.

The post-trade service is the source of truth — it processes fills and
writes portfolio state to Redis. The risk gateway reads from Redis
before every risk check so it operates on real data.

Key schema:
    portfolio:{run_id}        -> hash { current_equity, peak_equity, realized_pnl, unrealized_pnl, total_fees }
    positions:{run_id}:{SYM}  -> hash { quantity, avg_entry_price, realized_pnl, unrealized_pnl }
"""

from __future__ import annotations

import json
import logging

import redis as sync_redis

from quant_core.redis_utils import Keys

logger = logging.getLogger(__name__)

INITIAL_EQUITY = 100_000.0


# ---------------------------------------------------------------------------
# Writer (used by post-trade service)
# ---------------------------------------------------------------------------


def sync_portfolio_to_redis(
    r: sync_redis.Redis,
    run_id: str,
    positions: dict[str, dict],
    current_equity: float,
    peak_equity: float,
    realized_pnl: float,
    unrealized_pnl: float,
    total_fees: float,
) -> None:
    """Write full portfolio state to Redis.

    Called by the post-trade service after every fill is processed.
    Uses a pipeline for atomicity.
    """
    pipe = r.pipeline()

    # Portfolio summary
    pipe.hset(Keys.portfolio(run_id), mapping={
        "current_equity": str(current_equity),
        "peak_equity": str(peak_equity),
        "realized_pnl": str(realized_pnl),
        "unrealized_pnl": str(unrealized_pnl),
        "total_fees": str(total_fees),
    })

    # Per-symbol positions
    for symbol, pos in positions.items():
        pipe.hset(Keys.position(run_id, symbol), mapping={
            "quantity": str(pos.get("quantity", 0.0)),
            "avg_entry_price": str(pos.get("avg_entry_price", 0.0)),
            "realized_pnl": str(pos.get("realized_pnl", 0.0)),
            "unrealized_pnl": str(pos.get("unrealized_pnl", 0.0)),
        })

    pipe.execute()
    logger.debug("Synced portfolio state to Redis (run_id=%s)", run_id)


# ---------------------------------------------------------------------------
# Reader (used by risk gateway)
# ---------------------------------------------------------------------------


def read_portfolio_from_redis(
    r: sync_redis.Redis,
    run_id: str,
    symbols: list[str] | None = None,
) -> dict:
    """Read portfolio state from Redis.

    Returns a dict compatible with PortfolioState:
        {
            "positions": {"BTCUSD": 0.5, "ETHUSD": -1.2, ...},
            "current_equity": 100500.0,
            "peak_equity": 101000.0,
            "realized_pnl": 500.0,
            "unrealized_pnl": -200.0,
        }

    If no state is found in Redis, returns defaults (flat portfolio).
    """
    # Read portfolio summary
    summary = r.hgetall(Keys.portfolio(run_id))

    if not summary:
        logger.debug("No portfolio state in Redis for run_id=%s, using defaults", run_id)
        return {
            "positions": {},
            "current_equity": INITIAL_EQUITY,
            "peak_equity": INITIAL_EQUITY,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
        }

    current_equity = float(summary.get("current_equity", INITIAL_EQUITY))
    peak_equity = float(summary.get("peak_equity", INITIAL_EQUITY))
    realized_pnl = float(summary.get("realized_pnl", 0.0))
    unrealized_pnl = float(summary.get("unrealized_pnl", 0.0))

    # Read per-symbol positions
    positions: dict[str, float] = {}
    if symbols:
        for sym in symbols:
            pos_data = r.hgetall(Keys.position(run_id, sym.upper()))
            if pos_data:
                qty = float(pos_data.get("quantity", 0.0))
                if qty != 0.0:
                    positions[sym.upper()] = qty
    else:
        # Scan for all position keys matching this run_id
        prefix = f"positions:{run_id}:"
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=f"{prefix}*", count=100)
            for key in keys:
                symbol = key.split(":")[-1]
                pos_data = r.hgetall(key)
                if pos_data:
                    qty = float(pos_data.get("quantity", 0.0))
                    if qty != 0.0:
                        positions[symbol] = qty
            if cursor == 0:
                break

    return {
        "positions": positions,
        "current_equity": current_equity,
        "peak_equity": peak_equity,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
    }
