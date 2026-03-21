"""Kafka consumer for the Storage Service.

Consumes from raw.trades and raw.depth topics, deserializes messages
into model objects, and feeds them into the BatchWriter for bulk insert.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from quant_core.kafka_utils import QConsumer, TOPIC_RAW_TRADES, TOPIC_RAW_DEPTH
from quant_core.models import Trade, DepthUpdate

from storage_svc.batch_writer import BatchWriter, PendingTrade, PendingBookSnapshot

logger = logging.getLogger(__name__)

# How many top book levels to store as snapshots
BOOK_SNAPSHOT_DEPTH = 20

# Only snapshot the book every N updates (avoid storing every 100ms tick)
BOOK_SNAPSHOT_INTERVAL = 10


class StorageConsumer:
    """Consumes market data from Kafka and writes to TimescaleDB."""

    def __init__(self, consumer: QConsumer, writer: BatchWriter):
        self._consumer = consumer
        self._writer = writer
        self._book_update_counter: dict[str, int] = {}

    def process_batch(self) -> int:
        """Poll Kafka and process messages. Returns count processed."""
        messages = self._consumer.poll_messages(timeout=0.5, max_messages=500)
        if not messages:
            return 0

        for topic, key, value, headers in messages:
            try:
                backtest_id = headers.get("backtest_id")

                if topic == TOPIC_RAW_TRADES:
                    self._handle_trade(value, backtest_id)
                elif topic == TOPIC_RAW_DEPTH:
                    self._handle_depth(value, backtest_id)

            except Exception:
                logger.exception("Failed to process message from %s", topic)

        # Commit offsets after processing batch
        self._consumer.commit()
        return len(messages)

    def _handle_trade(self, raw: bytes, backtest_id: str | None) -> None:
        """Deserialize and buffer a trade for writing."""
        trade = Trade.from_json(raw)

        # Convert exchange timestamp (ms) to datetime
        ts = datetime.fromtimestamp(
            trade.timestamp_exchange / 1000.0, tz=timezone.utc
        )
        latency_us = None
        if trade.timestamp_ingested and trade.timestamp_exchange:
            latency_us = (trade.timestamp_ingested - trade.timestamp_exchange) * 1000

        self._writer.add_trade(
            PendingTrade(
                time=ts,
                symbol=trade.symbol,
                trade_id=trade.trade_id,
                price=trade.price,
                quantity=trade.quantity,
                is_buyer_maker=trade.is_buyer_maker,
                ingestion_latency_us=latency_us,
                backtest_id=backtest_id,
            )
        )

    def _handle_depth(self, raw: bytes, backtest_id: str | None) -> None:
        """Deserialize depth update and periodically snapshot the top levels."""
        depth = DepthUpdate.from_json(raw)
        symbol = depth.symbol

        # Increment counter for this symbol
        count = self._book_update_counter.get(symbol, 0) + 1
        self._book_update_counter[symbol] = count

        # Only snapshot every N updates
        if count % BOOK_SNAPSHOT_INTERVAL != 0:
            return

        # Take top N levels from the update
        bids = depth.bids[:BOOK_SNAPSHOT_DEPTH]
        asks = depth.asks[:BOOK_SNAPSHOT_DEPTH]

        if not bids or not asks:
            return

        bid_prices = [b[0] for b in bids]
        bid_sizes = [b[1] for b in bids]
        ask_prices = [a[0] for a in asks]
        ask_sizes = [a[1] for a in asks]

        best_bid = bid_prices[0] if bid_prices else 0.0
        best_ask = ask_prices[0] if ask_prices else 0.0
        spread = best_ask - best_bid
        mid_price = (best_ask + best_bid) / 2.0

        ts = datetime.fromtimestamp(
            depth.timestamp_exchange / 1000.0, tz=timezone.utc
        )

        self._writer.add_book_snapshot(
            PendingBookSnapshot(
                time=ts,
                symbol=symbol,
                bid_prices=bid_prices,
                bid_sizes=bid_sizes,
                ask_prices=ask_prices,
                ask_sizes=ask_sizes,
                spread=spread,
                mid_price=mid_price,
                backtest_id=backtest_id,
            )
        )
