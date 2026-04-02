"""Kafka producer and consumer helpers.

Wraps confluent-kafka with consistent serialization, error handling,
and backtest_id header injection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient, NewTopic

if TYPE_CHECKING:
    from collections.abc import Callable

    from quant_core.config import KafkaConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

TOPIC_RAW_TRADES = "raw.trades"
TOPIC_RAW_DEPTH = "raw.depth"
TOPIC_SIGNALS = "signals"
TOPIC_ORDERS = "orders"
TOPIC_ORDER_STATUS = "order.status"
TOPIC_FILLS = "fills"
TOPIC_RISK_EVENTS = "risk.events"
TOPIC_AUDIT = "audit.log"
TOPIC_HEARTBEAT = "system.heartbeat"


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


class QProducer:
    """Thin wrapper around confluent-kafka Producer with JSON serialization."""

    def __init__(self, config: KafkaConfig, backtest_id: str | None = None):
        self._producer = Producer(
            {
                "bootstrap.servers": config.bootstrap_servers,
                "acks": config.producer_acks,
                "linger.ms": config.producer_linger_ms,
                "batch.size": config.producer_batch_size,
                "compression.type": "lz4",
            }
        )
        self._backtest_id = backtest_id

    def produce(
        self,
        topic: str,
        value: str | bytes,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        on_delivery: Callable | None = None,
    ) -> None:
        """Produce a message, auto-injecting backtest_id header if set."""
        msg_headers = {}
        if self._backtest_id:
            msg_headers["backtest_id"] = self._backtest_id
        if headers:
            msg_headers.update(headers)

        kafka_headers = [(k, v.encode()) for k, v in msg_headers.items()] if msg_headers else None

        self._producer.produce(
            topic=topic,
            value=value.encode() if isinstance(value, str) else value,
            key=key.encode() if isinstance(key, str) else key,
            headers=kafka_headers,
            callback=on_delivery or self._default_callback,
        )

    def flush(self, timeout: float = 5.0) -> int:
        return self._producer.flush(timeout)

    def poll(self, timeout: float = 0.0) -> int:
        return self._producer.poll(timeout)

    @staticmethod
    def _default_callback(err, msg: Message) -> None:
        if err is not None:
            logger.error("Produce failed: %s [topic=%s]", err, msg.topic())


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class QConsumer:
    """Thin wrapper around confluent-kafka Consumer with deserialization."""

    def __init__(self, config: KafkaConfig, group_id: str, topics: list[str]):
        self._consumer = Consumer(
            {
                "bootstrap.servers": config.bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": config.consumer_auto_offset_reset,
                "enable.auto.commit": True,
                "max.poll.interval.ms": 300000,
            }
        )
        self._consumer.subscribe(topics)
        self._topics = topics
        logger.info("Consumer [%s] subscribed to %s", group_id, topics)

    def poll(self, timeout: float = 1.0) -> Message | None:
        """Poll for a single raw message. Returns confluent_kafka.Message or None."""
        return self._consumer.poll(timeout)

    def poll_messages(
        self,
        timeout: float = 1.0,
        max_messages: int = 500,
    ) -> list[tuple[str, str | None, bytes, dict[str, str]]]:
        """Poll for messages. Returns list of (topic, key, value, headers)."""
        messages = []
        msg = self._consumer.poll(timeout)
        if msg is None:
            return messages
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                return messages
            raise KafkaException(msg.error())

        messages.append(self._unpack(msg))

        # Drain available messages up to max_messages
        for _ in range(max_messages - 1):
            msg = self._consumer.poll(0.0)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Consumer error: %s", msg.error())
                continue
            messages.append(self._unpack(msg))

        return messages

    def commit(self) -> None:
        self._consumer.commit(asynchronous=False)

    def close(self) -> None:
        self._consumer.close()

    @staticmethod
    def _unpack(
        msg: Message,
    ) -> tuple[str, str | None, bytes, dict[str, str]]:
        key = msg.key().decode() if msg.key() else None
        headers = {}
        if msg.headers():
            headers = {k: v.decode() for k, v in msg.headers()}
        return (msg.topic(), key, msg.value(), headers)


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------


def ensure_topics(
    bootstrap_servers: str,
    topics: list[dict[str, Any]],
    timeout: float = 10.0,
) -> None:
    """Create topics if they don't exist. topics is a list of
    {"name": str, "partitions": int, "retention_ms": int} dicts.
    """
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = set(admin.list_topics(timeout=timeout).topics.keys())

    new_topics = []
    for t in topics:
        if t["name"] not in existing:
            config = {}
            if "retention_ms" in t:
                config["retention.ms"] = str(t["retention_ms"])
            new_topics.append(
                NewTopic(
                    topic=t["name"],
                    num_partitions=t.get("partitions", 6),
                    replication_factor=1,
                    config=config,
                )
            )

    if new_topics:
        futures = admin.create_topics(new_topics)
        for topic_name, future in futures.items():
            try:
                future.result()
                logger.info("Created topic: %s", topic_name)
            except Exception as e:
                logger.warning("Topic %s may already exist: %s", topic_name, e)
