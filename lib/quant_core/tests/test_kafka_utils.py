"""Tests for quant_core.kafka_utils — producer/consumer wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from quant_core.config import KafkaConfig
from quant_core.kafka_utils import (
    TOPIC_FILLS,
    TOPIC_HEARTBEAT,
    TOPIC_ORDERS,
    TOPIC_RAW_DEPTH,
    TOPIC_RAW_TRADES,
    TOPIC_RISK_EVENTS,
    TOPIC_SIGNALS,
    QConsumer,
    QProducer,
)

# -----------------------------------------------------------------------
# Topic constants
# -----------------------------------------------------------------------


class TestTopicNames:
    def test_all_topic_names_defined(self):
        assert TOPIC_RAW_TRADES == "raw.trades"
        assert TOPIC_RAW_DEPTH == "raw.depth"
        assert TOPIC_SIGNALS == "signals"
        assert TOPIC_ORDERS == "orders"
        assert TOPIC_FILLS == "fills"
        assert TOPIC_RISK_EVENTS == "risk.events"
        assert TOPIC_HEARTBEAT == "system.heartbeat"


# -----------------------------------------------------------------------
# QProducer
# -----------------------------------------------------------------------


class TestQProducer:
    @patch("quant_core.kafka_utils.Producer")
    def test_produce_encodes_string_value(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config)
        producer.produce(topic="raw.trades", value='{"test": true}', key="BTCUSDT")

        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["topic"] == "raw.trades"
        assert call_kwargs.kwargs["value"] == b'{"test": true}'
        assert call_kwargs.kwargs["key"] == b"BTCUSDT"

    @patch("quant_core.kafka_utils.Producer")
    def test_produce_passes_bytes_through(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config)
        producer.produce(topic="raw.trades", value=b"raw bytes", key=None)

        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["value"] == b"raw bytes"
        assert call_kwargs.kwargs["key"] is None

    @patch("quant_core.kafka_utils.Producer")
    def test_produce_injects_backtest_id_header(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config, backtest_id="bt-abc-123")
        producer.produce(topic="raw.trades", value="data")

        call_kwargs = mock_producer.produce.call_args
        headers = call_kwargs.kwargs["headers"]
        header_dict = {k: v.decode() for k, v in headers}
        assert header_dict["backtest_id"] == "bt-abc-123"

    @patch("quant_core.kafka_utils.Producer")
    def test_produce_no_headers_when_no_backtest(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config, backtest_id=None)
        producer.produce(topic="raw.trades", value="data")

        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["headers"] is None

    @patch("quant_core.kafka_utils.Producer")
    def test_produce_merges_custom_headers_with_backtest(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config, backtest_id="bt-123")
        producer.produce(
            topic="raw.trades",
            value="data",
            headers={"source": "replay"},
        )

        call_kwargs = mock_producer.produce.call_args
        headers = call_kwargs.kwargs["headers"]
        header_dict = {k: v.decode() for k, v in headers}
        assert header_dict["backtest_id"] == "bt-123"
        assert header_dict["source"] == "replay"

    @patch("quant_core.kafka_utils.Producer")
    def test_flush_delegates_to_producer(self, mock_producer_cls):
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0
        mock_producer_cls.return_value = mock_producer

        config = KafkaConfig(bootstrap_servers="localhost:9092")
        producer = QProducer(config)
        result = producer.flush(timeout=3.0)

        mock_producer.flush.assert_called_once_with(3.0)
        assert result == 0

    @patch("quant_core.kafka_utils.Producer")
    def test_producer_config_uses_lz4_compression(self, mock_producer_cls):
        config = KafkaConfig(bootstrap_servers="kafka:29092")
        QProducer(config)

        init_config = mock_producer_cls.call_args[0][0]
        assert init_config["compression.type"] == "lz4"
        assert init_config["bootstrap.servers"] == "kafka:29092"


# -----------------------------------------------------------------------
# QConsumer — unpack
# -----------------------------------------------------------------------


class TestQConsumerUnpack:
    def test_unpack_extracts_fields(self):
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "raw.trades"
        mock_msg.key.return_value = b"BTCUSDT"
        mock_msg.value.return_value = b'{"price": 42000}'
        mock_msg.headers.return_value = [("backtest_id", b"bt-123")]

        topic, key, value, headers = QConsumer._unpack(mock_msg)

        assert topic == "raw.trades"
        assert key == "BTCUSDT"
        assert value == b'{"price": 42000}'
        assert headers == {"backtest_id": "bt-123"}

    def test_unpack_handles_null_key(self):
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "raw.trades"
        mock_msg.key.return_value = None
        mock_msg.value.return_value = b"data"
        mock_msg.headers.return_value = None

        _topic, key, _value, headers = QConsumer._unpack(mock_msg)

        assert key is None
        assert headers == {}

    def test_unpack_handles_no_headers(self):
        mock_msg = MagicMock()
        mock_msg.topic.return_value = "raw.trades"
        mock_msg.key.return_value = b"KEY"
        mock_msg.value.return_value = b"data"
        mock_msg.headers.return_value = None

        _, _, _, headers = QConsumer._unpack(mock_msg)
        assert headers == {}
