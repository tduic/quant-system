"""Tests for market-data publisher — routing events to Kafka topics."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from quant_core.kafka_utils import TOPIC_RAW_TRADES, TOPIC_RAW_DEPTH
from quant_core.models import Trade, DepthUpdate
from market_data_svc.publisher import MarketDataPublisher


@pytest.fixture
def mock_producer() -> MagicMock:
    producer = MagicMock()
    producer.poll.return_value = 0
    return producer


@pytest.fixture
def publisher(mock_producer: MagicMock) -> MarketDataPublisher:
    return MarketDataPublisher(mock_producer)


class TestPublishTrade:
    def test_publishes_to_raw_trades_topic(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        trade = Trade(symbol="BTCUSDT", price=42000.0, quantity=0.1)
        publisher.publish(trade)

        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["topic"] == TOPIC_RAW_TRADES

    def test_uses_symbol_as_key(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        trade = Trade(symbol="ETHUSDT", price=3000.0, quantity=1.0)
        publisher.publish(trade)

        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["key"] == "ETHUSDT"

    def test_value_is_json_string(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        trade = Trade(symbol="BTCUSDT", price=42000.0, quantity=0.1)
        publisher.publish(trade)

        call_kwargs = mock_producer.produce.call_args
        value = call_kwargs.kwargs["value"]
        assert isinstance(value, str)
        assert "42000.0" in value
        assert "BTCUSDT" in value

    def test_increments_trade_count(
        self, publisher: MarketDataPublisher
    ):
        assert publisher.stats["trades_published"] == 0
        publisher.publish(Trade(symbol="BTCUSDT"))
        publisher.publish(Trade(symbol="BTCUSDT"))
        assert publisher.stats["trades_published"] == 2

    def test_calls_poll_after_produce(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        publisher.publish(Trade(symbol="BTCUSDT"))
        mock_producer.poll.assert_called_once_with(0.0)


class TestPublishDepthUpdate:
    def test_publishes_to_raw_depth_topic(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        depth = DepthUpdate(symbol="BTCUSDT")
        publisher.publish(depth)

        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["topic"] == TOPIC_RAW_DEPTH

    def test_uses_symbol_as_key(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        depth = DepthUpdate(symbol="SOLUSDT")
        publisher.publish(depth)

        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["key"] == "SOLUSDT"

    def test_increments_depth_count(
        self, publisher: MarketDataPublisher
    ):
        assert publisher.stats["depth_updates_published"] == 0
        publisher.publish(DepthUpdate(symbol="BTCUSDT"))
        publisher.publish(DepthUpdate(symbol="BTCUSDT"))
        publisher.publish(DepthUpdate(symbol="BTCUSDT"))
        assert publisher.stats["depth_updates_published"] == 3


class TestPublisherStats:
    def test_initial_stats_are_zero(self, publisher: MarketDataPublisher):
        assert publisher.stats == {
            "trades_published": 0,
            "depth_updates_published": 0,
        }

    def test_stats_track_both_types(self, publisher: MarketDataPublisher):
        publisher.publish(Trade(symbol="BTCUSDT"))
        publisher.publish(DepthUpdate(symbol="BTCUSDT"))
        publisher.publish(Trade(symbol="BTCUSDT"))

        assert publisher.stats["trades_published"] == 2
        assert publisher.stats["depth_updates_published"] == 1


class TestPublisherFlush:
    def test_flush_delegates_to_producer(
        self, publisher: MarketDataPublisher, mock_producer: MagicMock
    ):
        mock_producer.flush.return_value = 0
        publisher.flush()
        mock_producer.flush.assert_called_once_with(timeout=10.0)
