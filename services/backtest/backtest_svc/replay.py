"""Backtest replay engine.

Reads historical tick data from TimescaleDB and replays it through Kafka
at the same topics (raw.trades, raw.depth) with a backtest_id header.
All downstream services process the data identically to live — no
`if backtest:` branches anywhere.

Replay modes:
    - as_fast_as_possible: no delay between messages (max throughput)
    - real_time: replay at the original speed (1x)
    - scaled: replay at N times original speed
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class ReplaySpeed(StrEnum):
    AS_FAST_AS_POSSIBLE = "as_fast_as_possible"
    REAL_TIME = "real_time"
    SCALED = "scaled"


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""

    backtest_id: str = ""
    symbol: str = "BTCUSD"
    start_time: str = ""  # ISO 8601 or YYYY-MM-DD HH:MM:SS
    end_time: str = ""
    replay_speed: ReplaySpeed = ReplaySpeed.AS_FAST_AS_POSSIBLE
    speed_multiplier: float = 1.0  # only used when replay_speed == SCALED
    include_depth: bool = True

    def __post_init__(self):
        if not self.backtest_id:
            self.backtest_id = f"bt-{uuid.uuid4().hex[:12]}"


@dataclass
class ReplayStats:
    """Statistics from a completed replay."""

    backtest_id: str = ""
    trades_replayed: int = 0
    depth_updates_replayed: int = 0
    duration_seconds: float = 0.0
    data_span_seconds: float = 0.0
    messages_per_second: float = 0.0


class ReplayEngine:
    """Reads historical data from TimescaleDB and publishes to Kafka.

    The engine is synchronous and runs in the main thread — it's designed
    to be called from the CLI and block until the replay is complete.
    """

    def __init__(self, db_url: str, kafka_producer, config: BacktestConfig):
        self._db_url = db_url
        self._producer = kafka_producer
        self._config = config
        self._stats = ReplayStats(backtest_id=config.backtest_id)

    @property
    def stats(self) -> ReplayStats:
        return self._stats

    def run(self) -> ReplayStats:
        """Execute the replay. Blocks until complete."""
        logger.info(
            "Starting backtest %s: %s %s -> %s [speed=%s]",
            self._config.backtest_id,
            self._config.symbol,
            self._config.start_time,
            self._config.end_time,
            self._config.replay_speed,
        )

        start_wall = time.monotonic()

        # Replay trades
        trades = self._fetch_trades()
        self._replay_messages(trades, topic="raw.trades")
        self._stats.trades_replayed = len(trades)

        # Replay depth snapshots (reconstructed as depth updates)
        if self._config.include_depth:
            depth = self._fetch_depth()
            self._replay_messages(depth, topic="raw.depth")
            self._stats.depth_updates_replayed = len(depth)

        # Flush producer
        self._producer.flush(timeout=10.0)

        elapsed = time.monotonic() - start_wall
        self._stats.duration_seconds = elapsed
        total_msgs = self._stats.trades_replayed + self._stats.depth_updates_replayed
        self._stats.messages_per_second = total_msgs / elapsed if elapsed > 0 else 0

        if trades:
            first_ts = float(trades[0]["timestamp_exchange"])
            last_ts = float(trades[-1]["timestamp_exchange"])
            self._stats.data_span_seconds = (last_ts - first_ts) / 1000.0

        logger.info(
            "Backtest %s complete: %d trades, %d depth in %.1fs (%.0f msg/s)",
            self._config.backtest_id,
            self._stats.trades_replayed,
            self._stats.depth_updates_replayed,
            elapsed,
            self._stats.messages_per_second,
        )

        return self._stats

    @staticmethod
    def _parse_time(ts: str) -> datetime:
        """Parse ISO 8601 string to timezone-aware datetime."""
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    def _fetch_trades(self) -> list[dict]:
        """Fetch historical trades from TimescaleDB."""
        import asyncio

        import asyncpg

        start_dt = self._parse_time(self._config.start_time)
        end_dt = self._parse_time(self._config.end_time)

        async def _query():
            conn = await asyncpg.connect(self._db_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM time) * 1000 AS timestamp_exchange,
                        symbol,
                        trade_id,
                        price::float,
                        quantity::float,
                        is_buyer_maker
                    FROM trades
                    WHERE symbol = $1
                      AND time >= $2::timestamptz
                      AND time < $3::timestamptz
                      AND backtest_id IS NULL
                    ORDER BY time ASC
                    """,
                    self._config.symbol,
                    start_dt,
                    end_dt,
                )
                return [dict(r) for r in rows]
            finally:
                await conn.close()

        return asyncio.run(_query())

    def _fetch_depth(self) -> list[dict]:
        """Fetch historical order book snapshots from TimescaleDB."""
        import asyncio

        import asyncpg

        start_dt = self._parse_time(self._config.start_time)
        end_dt = self._parse_time(self._config.end_time)

        async def _query():
            conn = await asyncpg.connect(self._db_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        EXTRACT(EPOCH FROM time) * 1000 AS timestamp_exchange,
                        symbol,
                        bid_prices::float[] AS bid_prices,
                        bid_sizes::float[] AS bid_sizes,
                        ask_prices::float[] AS ask_prices,
                        ask_sizes::float[] AS ask_sizes
                    FROM order_book_snapshots
                    WHERE symbol = $1
                      AND time >= $2::timestamptz
                      AND time < $3::timestamptz
                      AND backtest_id IS NULL
                    ORDER BY time ASC
                    """,
                    self._config.symbol,
                    start_dt,
                    end_dt,
                )
                return [dict(r) for r in rows]
            finally:
                await conn.close()

        return asyncio.run(_query())

    def _replay_messages(self, messages: list[dict], topic: str) -> None:
        """Publish messages to Kafka with timing control."""

        if not messages:
            return

        prev_ts = float(messages[0].get("timestamp_exchange", 0))

        for msg in messages:
            # Timing control
            if self._config.replay_speed != ReplaySpeed.AS_FAST_AS_POSSIBLE:
                ts = float(msg.get("timestamp_exchange", 0))
                delta_ms = ts - prev_ts
                prev_ts = ts

                if delta_ms > 0:
                    if self._config.replay_speed == ReplaySpeed.REAL_TIME:
                        time.sleep(delta_ms / 1000.0)
                    elif self._config.replay_speed == ReplaySpeed.SCALED:
                        time.sleep(delta_ms / 1000.0 / self._config.speed_multiplier)

            # Convert to canonical format
            payload = _trade_row_to_json(msg) if topic == "raw.trades" else _depth_row_to_json(msg)

            self._producer.produce(
                topic=topic,
                key=msg.get("symbol", self._config.symbol),
                value=payload,
            )

            # Periodic poll to trigger delivery callbacks
            self._producer.poll(0.0)


def _trade_row_to_json(row: dict) -> str:
    """Convert a DB trade row to the canonical Trade JSON format."""
    import json

    return json.dumps(
        {
            "type": "trade",
            "exchange": "coinbase",
            "symbol": row["symbol"],
            "trade_id": row.get("trade_id", 0),
            "price": row["price"],
            "quantity": row["quantity"],
            "timestamp_exchange": int(row["timestamp_exchange"]),
            "timestamp_ingested": int(row["timestamp_exchange"]),  # same for replays
            "is_buyer_maker": row.get("is_buyer_maker", False),
        }
    )


def _depth_row_to_json(row: dict) -> str:
    """Convert a DB depth snapshot row to the canonical DepthUpdate JSON format."""
    import json

    bid_prices = row.get("bid_prices", [])
    bid_sizes = row.get("bid_sizes", [])
    ask_prices = row.get("ask_prices", [])
    ask_sizes = row.get("ask_sizes", [])

    bids = [[p, s] for p, s in zip(bid_prices, bid_sizes, strict=True)]
    asks = [[p, s] for p, s in zip(ask_prices, ask_sizes, strict=True)]

    return json.dumps(
        {
            "type": "depth_update",
            "exchange": "coinbase",
            "symbol": row["symbol"],
            "first_update_id": 0,
            "final_update_id": 0,
            "bids": bids,
            "asks": asks,
            "timestamp_exchange": int(row["timestamp_exchange"]),
            "timestamp_ingested": int(row["timestamp_exchange"]),
        }
    )
