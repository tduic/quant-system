"""Kafka publisher for normalized market data events.

Routes Trade events to raw.trades and DepthUpdate events to raw.depth,
using the symbol as the partition key (ensures per-symbol ordering).
"""

from __future__ import annotations

import logging

from quant_core.kafka_utils import TOPIC_RAW_DEPTH, TOPIC_RAW_TRADES, QProducer
from quant_core.models import DepthUpdate, Trade

logger = logging.getLogger(__name__)


class MarketDataPublisher:
    """Publishes normalized market data to Kafka."""

    def __init__(self, producer: QProducer):
        self._producer = producer
        self._trade_count = 0
        self._depth_count = 0

    def publish(self, event: Trade | DepthUpdate) -> None:
        """Route an event to the appropriate Kafka topic."""
        if isinstance(event, Trade):
            self._producer.produce(
                topic=TOPIC_RAW_TRADES,
                key=event.symbol,
                value=event.to_json(),
            )
            self._trade_count += 1

        elif isinstance(event, DepthUpdate):
            self._producer.produce(
                topic=TOPIC_RAW_DEPTH,
                key=event.symbol,
                value=event.to_json(),
            )
            self._depth_count += 1

        # Periodically trigger delivery callbacks
        self._producer.poll(0.0)

    def flush(self) -> None:
        """Flush any pending messages."""
        remaining = self._producer.flush(timeout=10.0)
        if remaining > 0:
            logger.warning("%d messages still in queue after flush", remaining)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "trades_published": self._trade_count,
            "depth_updates_published": self._depth_count,
        }
