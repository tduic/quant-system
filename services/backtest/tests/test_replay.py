"""Tests for backtest_svc.replay — replay engine and helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from backtest_svc.replay import (
    BacktestConfig,
    ReplayEngine,
    ReplaySpeed,
    _depth_row_to_json,
    _trade_row_to_json,
)


class TestBacktestConfig:
    def test_auto_generates_backtest_id(self):
        config = BacktestConfig()
        assert config.backtest_id.startswith("bt-")
        assert len(config.backtest_id) > 5

    def test_custom_backtest_id_preserved(self):
        config = BacktestConfig(backtest_id="my-test-123")
        assert config.backtest_id == "my-test-123"

    def test_defaults(self):
        config = BacktestConfig()
        assert config.symbol == "BTCUSD"
        assert config.replay_speed == ReplaySpeed.AS_FAST_AS_POSSIBLE
        assert config.include_depth is True

    def test_unique_ids(self):
        c1 = BacktestConfig()
        c2 = BacktestConfig()
        assert c1.backtest_id != c2.backtest_id


class TestReplaySpeed:
    def test_speed_values(self):
        assert ReplaySpeed.AS_FAST_AS_POSSIBLE == "as_fast_as_possible"
        assert ReplaySpeed.REAL_TIME == "real_time"
        assert ReplaySpeed.SCALED == "scaled"


class TestTradeRowToJson:
    def test_converts_trade_row(self):
        row = {
            "symbol": "BTCUSD",
            "trade_id": 123,
            "price": 80000.0,
            "quantity": 0.001,
            "timestamp_exchange": 1711000000000.0,
            "is_buyer_maker": False,
        }
        result = json.loads(_trade_row_to_json(row))
        assert result["type"] == "trade"
        assert result["exchange"] == "coinbase"
        assert result["symbol"] == "BTCUSD"
        assert result["price"] == 80000.0
        assert result["quantity"] == 0.001
        assert result["trade_id"] == 123
        assert result["is_buyer_maker"] is False

    def test_handles_missing_trade_id(self):
        row = {
            "symbol": "BTCUSD",
            "price": 80000.0,
            "quantity": 0.001,
            "timestamp_exchange": 1711000000000.0,
        }
        result = json.loads(_trade_row_to_json(row))
        assert result["trade_id"] == 0


class TestDepthRowToJson:
    def test_converts_depth_row(self):
        row = {
            "symbol": "BTCUSD",
            "bid_prices": [80000.0, 79999.0],
            "bid_sizes": [1.0, 2.0],
            "ask_prices": [80001.0, 80002.0],
            "ask_sizes": [1.5, 0.5],
            "timestamp_exchange": 1711000000000.0,
        }
        result = json.loads(_depth_row_to_json(row))
        assert result["type"] == "depth_update"
        assert result["symbol"] == "BTCUSD"
        assert len(result["bids"]) == 2
        assert len(result["asks"]) == 2
        assert result["bids"][0] == [80000.0, 1.0]
        assert result["asks"][0] == [80001.0, 1.5]

    def test_empty_depth(self):
        row = {
            "symbol": "BTCUSD",
            "bid_prices": [],
            "bid_sizes": [],
            "ask_prices": [],
            "ask_sizes": [],
            "timestamp_exchange": 1711000000000.0,
        }
        result = json.loads(_depth_row_to_json(row))
        assert result["bids"] == []
        assert result["asks"] == []


class TestReplayEngine:
    def test_replay_empty_data(self):
        """Replay with no data should complete with zero counts."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        config = BacktestConfig(
            backtest_id="test-empty",
            symbol="BTCUSD",
            start_time="2026-01-01T00:00:00",
            end_time="2026-01-01T01:00:00",
        )

        engine = ReplayEngine(
            db_url="postgresql://test:test@localhost/test",
            kafka_producer=mock_producer,
            config=config,
        )

        # Mock the fetch methods to return empty
        engine._fetch_trades = MagicMock(return_value=[])
        engine._fetch_depth = MagicMock(return_value=[])

        stats = engine.run()
        assert stats.trades_replayed == 0
        assert stats.depth_updates_replayed == 0
        assert stats.backtest_id == "test-empty"

    def test_replay_publishes_trades(self):
        """Trades should be published to raw.trades topic."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        config = BacktestConfig(
            backtest_id="test-trades",
            symbol="BTCUSD",
            start_time="2026-01-01",
            end_time="2026-01-02",
        )

        engine = ReplayEngine(
            db_url="test://",
            kafka_producer=mock_producer,
            config=config,
        )

        fake_trades = [
            {
                "symbol": "BTCUSD",
                "trade_id": 1,
                "price": 80000.0,
                "quantity": 0.001,
                "timestamp_exchange": 1000.0,
                "is_buyer_maker": False,
            },
            {
                "symbol": "BTCUSD",
                "trade_id": 2,
                "price": 80010.0,
                "quantity": 0.002,
                "timestamp_exchange": 2000.0,
                "is_buyer_maker": True,
            },
        ]

        engine._fetch_trades = MagicMock(return_value=fake_trades)
        engine._fetch_depth = MagicMock(return_value=[])

        stats = engine.run()

        assert stats.trades_replayed == 2
        assert mock_producer.produce.call_count == 2
        # Verify topic
        first_call = mock_producer.produce.call_args_list[0]
        assert first_call.kwargs["topic"] == "raw.trades"

    def test_replay_publishes_depth(self):
        """Depth updates should be published to raw.depth topic."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        config = BacktestConfig(
            backtest_id="test-depth",
            symbol="BTCUSD",
            start_time="2026-01-01",
            end_time="2026-01-02",
            include_depth=True,
        )

        engine = ReplayEngine(
            db_url="test://",
            kafka_producer=mock_producer,
            config=config,
        )

        engine._fetch_trades = MagicMock(return_value=[])
        engine._fetch_depth = MagicMock(
            return_value=[
                {
                    "symbol": "BTCUSD",
                    "bid_prices": [80000.0],
                    "bid_sizes": [1.0],
                    "ask_prices": [80001.0],
                    "ask_sizes": [1.0],
                    "timestamp_exchange": 1000.0,
                },
            ]
        )

        stats = engine.run()
        assert stats.depth_updates_replayed == 1

    def test_no_depth_flag(self):
        """include_depth=False should skip depth replay."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        config = BacktestConfig(
            backtest_id="test-no-depth",
            symbol="BTCUSD",
            start_time="2026-01-01",
            end_time="2026-01-02",
            include_depth=False,
        )

        engine = ReplayEngine(db_url="test://", kafka_producer=mock_producer, config=config)
        engine._fetch_trades = MagicMock(return_value=[])
        engine._fetch_depth = MagicMock(return_value=[])

        stats = engine.run()
        engine._fetch_depth.assert_not_called()
        assert stats.depth_updates_replayed == 0

    def test_stats_throughput(self):
        """Throughput should be computed correctly."""
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0

        config = BacktestConfig(
            backtest_id="test-throughput", symbol="BTCUSD", start_time="2026-01-01", end_time="2026-01-02"
        )

        engine = ReplayEngine(db_url="test://", kafka_producer=mock_producer, config=config)

        trades = [
            {
                "symbol": "BTCUSD",
                "trade_id": i,
                "price": 80000.0 + i,
                "quantity": 0.001,
                "timestamp_exchange": float(i * 1000),
                "is_buyer_maker": False,
            }
            for i in range(100)
        ]

        engine._fetch_trades = MagicMock(return_value=trades)
        engine._fetch_depth = MagicMock(return_value=[])

        stats = engine.run()
        assert stats.trades_replayed == 100
        assert stats.messages_per_second > 0
        assert stats.data_span_seconds > 0
