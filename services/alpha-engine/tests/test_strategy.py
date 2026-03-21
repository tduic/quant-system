"""Tests for alpha_engine_svc.strategy — base class and registry."""

from __future__ import annotations

import pytest

from alpha_engine_svc.strategy import BaseStrategy, StrategyRegistry
from quant_core.models import DepthUpdate, Signal, Trade


class DummyStrategy(BaseStrategy):
    """Concrete strategy for testing."""

    def __init__(self, strategy_id: str = "dummy", symbol: str = "BTCUSD"):
        super().__init__(strategy_id=strategy_id, symbol=symbol)
        self.trade_count = 0
        self.book_count = 0

    def on_trade(self, trade: Trade) -> Signal | None:
        self.trade_count += 1
        if self.trade_count >= 3:
            return Signal(strategy_id=self.strategy_id, symbol=self.symbol, side="BUY")
        return None

    def on_book_update(self, update: DepthUpdate) -> Signal | None:
        self.book_count += 1
        return None


class TestBaseStrategy:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseStrategy(strategy_id="test", symbol="BTCUSD")

    def test_concrete_strategy_has_attributes(self):
        s = DummyStrategy()
        assert s.strategy_id == "dummy"
        assert s.symbol == "BTCUSD"
        assert s.params == {}

    def test_on_trade_returns_signal_after_threshold(self):
        s = DummyStrategy()
        trade = Trade(symbol="BTCUSD", price=100.0)
        assert s.on_trade(trade) is None
        assert s.on_trade(trade) is None
        signal = s.on_trade(trade)
        assert isinstance(signal, Signal)
        assert signal.side == "BUY"

    def test_on_book_update_returns_none(self):
        s = DummyStrategy()
        update = DepthUpdate(symbol="BTCUSD")
        assert s.on_book_update(update) is None

    def test_on_signal_fill_default_noop(self):
        s = DummyStrategy()
        # Should not raise
        s.on_signal_fill("sig-123", 42000.0)

    def test_params_passed_through(self):
        s = DummyStrategy.__new__(DummyStrategy)
        BaseStrategy.__init__(s, strategy_id="test", symbol="BTCUSD", params={"window": 50})
        assert s.params["window"] == 50


class TestStrategyRegistry:
    def test_register_and_get(self):
        reg = StrategyRegistry()
        s = DummyStrategy(strategy_id="s1")
        reg.register(s)
        assert reg.get("s1") is s

    def test_get_nonexistent_returns_none(self):
        reg = StrategyRegistry()
        assert reg.get("nope") is None

    def test_unregister(self):
        reg = StrategyRegistry()
        s = DummyStrategy(strategy_id="s1")
        reg.register(s)
        reg.unregister("s1")
        assert reg.get("s1") is None

    def test_unregister_nonexistent_is_noop(self):
        reg = StrategyRegistry()
        reg.unregister("nope")  # Should not raise

    def test_all_returns_all_strategies(self):
        reg = StrategyRegistry()
        reg.register(DummyStrategy(strategy_id="s1"))
        reg.register(DummyStrategy(strategy_id="s2"))
        assert len(reg.all) == 2

    def test_strategies_for_symbol(self):
        reg = StrategyRegistry()
        reg.register(DummyStrategy(strategy_id="s1", symbol="BTCUSD"))
        reg.register(DummyStrategy(strategy_id="s2", symbol="ETHUSD"))
        reg.register(DummyStrategy(strategy_id="s3", symbol="BTCUSD"))
        btc = reg.strategies_for_symbol("BTCUSD")
        assert len(btc) == 2
        assert all(s.symbol == "BTCUSD" for s in btc)
