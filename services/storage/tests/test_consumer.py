"""Tests for storage consumer — Kafka message deserialization and routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from quant_core.kafka_utils import TOPIC_RAW_TRADES, TOPIC_RAW_DEPTH
from quant_core.models import Trade, DepthUpdate
from storage_svc.consumer import StorageConsumer, BOOK_SNAPSHOT_INTERVAL, BOOK_SNAPSHOT_DEPTH
from storage_svc.batch_writer import BatchWriter


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def mock_writer() -> MagicMock:
    return MagicMock(spec=BatchWriter)


@pytest.fixture
def mock_kafka_consumer() -> MagicMock:
    consumer = MagicMock()
    consumer.poll_messages.return_value = []
    return consumer


@pytest.fixture
def consumer(
    mock_kafka_consumer: MagicMock, mock_writer: MagicMock
) -> StorageConsumer:
    return StorageConsumer(mock_kafka_consumer, mock_writer)


def make_trade_message(
    symbol: str = "BTCUSDT",
    price: float = 42000.0,
    trade_id: int = 1,
) -> tuple[str, str, bytes, dict]:
    trade = Trade(
        symbol=symbol,
        trade_id=trade_id,
        price=price,
        quantity=0.001,
        timestamp_exchange=1672515782136,
        timestamp_ingested=1672515782140,
        is_buyer_maker=False,
    )
    return (TOPIC_RAW_TRADES, symbol, trade.to_json().encode(), {})


def make_depth_message(
    symbol: str = "BTCUSDT",
    num_levels: int = 25,
) -> tuple[str, str, bytes, dict]:
    bids = [[42000.0 - i * 0.5, 1.0 + i * 0.1] for i in range(num_levels)]
    asks = [[42001.0 + i * 0.5, 0.5 + i * 0.1] for i in range(num_levels)]
    depth = DepthUpdate(
        symbol=symbol,
        first_update_id=100,
        final_update_id=105,
        bids=bids,
        asks=asks,
        timestamp_exchange=1672515782136,
        timestamp_ingested=1672515782140,
    )
    return (TOPIC_RAW_DEPTH, symbol, depth.to_json().encode(), {})


# -----------------------------------------------------------------------
# Trade processing
# -----------------------------------------------------------------------

class TestTradeProcessing:
    def test_trade_message_adds_to_writer(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [make_trade_message()]
        consumer.process_batch()

        mock_writer.add_trade.assert_called_once()
        pending = mock_writer.add_trade.call_args[0][0]
        assert pending.symbol == "BTCUSDT"
        assert pending.price == pytest.approx(42000.0)

    def test_trade_computes_ingestion_latency(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [make_trade_message()]
        consumer.process_batch()

        pending = mock_writer.add_trade.call_args[0][0]
        # (1672515782140 - 1672515782136) * 1000 = 4000 us
        assert pending.ingestion_latency_us == 4000

    def test_trade_time_is_utc_datetime(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [make_trade_message()]
        consumer.process_batch()

        pending = mock_writer.add_trade.call_args[0][0]
        assert pending.time.tzinfo is not None  # timezone-aware

    def test_multiple_trades_in_batch(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [
            make_trade_message(trade_id=1),
            make_trade_message(trade_id=2),
            make_trade_message(trade_id=3),
        ]
        consumer.process_batch()

        assert mock_writer.add_trade.call_count == 3

    def test_backtest_id_passed_through(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        topic, key, value, _ = make_trade_message()
        headers = {"backtest_id": "bt-abc"}
        mock_kafka_consumer.poll_messages.return_value = [
            (topic, key, value, headers)
        ]
        consumer.process_batch()

        pending = mock_writer.add_trade.call_args[0][0]
        assert pending.backtest_id == "bt-abc"


# -----------------------------------------------------------------------
# Depth processing
# -----------------------------------------------------------------------

class TestDepthProcessing:
    def test_depth_not_snapshotted_until_interval(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        """First N-1 depth updates should not trigger a snapshot."""
        messages = [make_depth_message() for _ in range(BOOK_SNAPSHOT_INTERVAL - 1)]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        mock_writer.add_book_snapshot.assert_not_called()

    def test_depth_snapshotted_at_interval(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        """The Nth depth update should trigger a snapshot."""
        messages = [make_depth_message() for _ in range(BOOK_SNAPSHOT_INTERVAL)]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        mock_writer.add_book_snapshot.assert_called_once()

    def test_snapshot_has_correct_depth(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        messages = [make_depth_message(num_levels=30) for _ in range(BOOK_SNAPSHOT_INTERVAL)]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        snap = mock_writer.add_book_snapshot.call_args[0][0]
        assert len(snap.bid_prices) == BOOK_SNAPSHOT_DEPTH
        assert len(snap.ask_prices) == BOOK_SNAPSHOT_DEPTH

    def test_snapshot_computes_spread(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        messages = [make_depth_message() for _ in range(BOOK_SNAPSHOT_INTERVAL)]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        snap = mock_writer.add_book_snapshot.call_args[0][0]
        assert snap.spread == pytest.approx(1.0)  # 42001.0 - 42000.0
        assert snap.mid_price == pytest.approx(42000.5)

    def test_snapshot_per_symbol_counting(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        """Each symbol has its own snapshot counter."""
        btc_msgs = [make_depth_message("BTCUSDT") for _ in range(BOOK_SNAPSHOT_INTERVAL)]
        eth_msgs = [make_depth_message("ETHUSDT") for _ in range(BOOK_SNAPSHOT_INTERVAL - 1)]

        mock_kafka_consumer.poll_messages.return_value = btc_msgs + eth_msgs
        consumer.process_batch()

        # BTC hit the interval, ETH did not
        assert mock_writer.add_book_snapshot.call_count == 1
        snap = mock_writer.add_book_snapshot.call_args[0][0]
        assert snap.symbol == "BTCUSDT"

    def test_empty_bids_asks_not_snapshotted(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        """Depth updates with no bids/asks should be skipped."""
        depth = DepthUpdate(
            symbol="BTCUSDT",
            bids=[],
            asks=[],
            timestamp_exchange=1672515782136,
            timestamp_ingested=1672515782140,
        )
        messages = [
            (TOPIC_RAW_DEPTH, "BTCUSDT", depth.to_json().encode(), {})
            for _ in range(BOOK_SNAPSHOT_INTERVAL)
        ]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        mock_writer.add_book_snapshot.assert_not_called()


# -----------------------------------------------------------------------
# Batch processing mechanics
# -----------------------------------------------------------------------

class TestBatchProcessing:
    def test_returns_zero_when_no_messages(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = []
        assert consumer.process_batch() == 0

    def test_returns_message_count(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [
            make_trade_message(trade_id=1),
            make_trade_message(trade_id=2),
        ]
        assert consumer.process_batch() == 2

    def test_commits_after_processing(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = [make_trade_message()]
        consumer.process_batch()
        mock_kafka_consumer.commit.assert_called_once()

    def test_does_not_commit_when_no_messages(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
    ):
        mock_kafka_consumer.poll_messages.return_value = []
        consumer.process_batch()
        mock_kafka_consumer.commit.assert_not_called()

    def test_mixed_trade_and_depth_batch(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        messages = [make_trade_message()] + [
            make_depth_message() for _ in range(BOOK_SNAPSHOT_INTERVAL)
        ]
        mock_kafka_consumer.poll_messages.return_value = messages
        consumer.process_batch()

        mock_writer.add_trade.assert_called_once()
        mock_writer.add_book_snapshot.assert_called_once()

    def test_bad_message_does_not_crash_batch(
        self,
        consumer: StorageConsumer,
        mock_kafka_consumer: MagicMock,
        mock_writer: MagicMock,
    ):
        """A malformed message should be skipped, not crash the whole batch."""
        mock_kafka_consumer.poll_messages.return_value = [
            (TOPIC_RAW_TRADES, "BTCUSDT", b"not valid json", {}),
            make_trade_message(trade_id=2),
        ]
        count = consumer.process_batch()

        # Should still process the good message
        assert count == 2
        assert mock_writer.add_trade.call_count == 1
