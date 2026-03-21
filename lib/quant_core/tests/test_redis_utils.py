"""Tests for quant_core.redis_utils — key schema and helpers."""

from __future__ import annotations

from quant_core.redis_utils import Keys


class TestKeys:
    """Verify the Redis key schema produces correct patterns."""

    # Order book keys
    def test_book_bids(self):
        assert Keys.book_bids("BTCUSDT") == "book:BTCUSDT:bids"

    def test_book_asks(self):
        assert Keys.book_asks("BTCUSDT") == "book:BTCUSDT:asks"

    def test_book_mid(self):
        assert Keys.book_mid("BTCUSDT") == "book:BTCUSDT:mid_price"

    def test_book_spread(self):
        assert Keys.book_spread("BTCUSDT") == "book:BTCUSDT:spread"

    def test_book_last_update(self):
        assert Keys.book_last_update("BTCUSDT") == "book:BTCUSDT:last_update"

    # Feature keys
    def test_feature(self):
        assert Keys.feature("BTCUSDT", "vwap_60s") == "features:BTCUSDT:vwap_60s"

    def test_feature_different_names(self):
        assert Keys.feature("ETHUSDT", "volatility") == "features:ETHUSDT:volatility"
        assert Keys.feature("ETHUSDT", "book_imbalance") == "features:ETHUSDT:book_imbalance"

    # Position / portfolio keys
    def test_position(self):
        assert Keys.position("live", "BTCUSDT") == "positions:live:BTCUSDT"

    def test_position_with_backtest_id(self):
        assert Keys.position("bt-abc", "BTCUSDT") == "positions:bt-abc:BTCUSDT"

    def test_portfolio(self):
        assert Keys.portfolio("live") == "portfolio:live"

    # Risk keys
    def test_risk_limits(self):
        assert Keys.risk_limits("live") == "risk:limits:live"

    def test_circuit_breaker(self):
        assert Keys.circuit_breaker("live") == "risk:circuit_breaker:live"

    def test_order_timestamps(self):
        assert Keys.order_timestamps("live", "BTCUSDT") == "risk:order_timestamps:live:BTCUSDT"

    # Heartbeat
    def test_heartbeat(self):
        assert Keys.heartbeat("market-data") == "heartbeat:market-data"

    # Namespace isolation
    def test_different_run_ids_produce_different_keys(self):
        live_key = Keys.position("live", "BTCUSDT")
        backtest_key = Keys.position("bt-123", "BTCUSDT")
        assert live_key != backtest_key
        assert "live" in live_key
        assert "bt-123" in backtest_key
