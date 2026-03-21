"""Tests for alpha_engine_svc.feature_engine — rolling feature computation."""

from __future__ import annotations

import pytest

from alpha_engine_svc.feature_engine import FeatureEngine


@pytest.fixture
def engine() -> FeatureEngine:
    return FeatureEngine(symbol="BTCUSD", window_size=10)


class TestFeatureEngineEmpty:
    def test_compute_empty_returns_defaults(self, engine: FeatureEngine):
        f = engine.compute()
        assert f.symbol == "BTCUSD"
        assert f.vwap == 0.0
        assert f.volatility == 0.0
        assert f.trade_rate == 0.0


class TestVWAP:
    def test_single_trade_vwap_equals_price(self, engine: FeatureEngine):
        engine.on_trade(100.0, 1.0, False, 1000)
        f = engine.compute()
        assert f.vwap == pytest.approx(100.0)

    def test_vwap_weighted_by_volume(self, engine: FeatureEngine):
        engine.on_trade(100.0, 3.0, False, 1000)
        engine.on_trade(200.0, 1.0, False, 2000)
        f = engine.compute()
        # VWAP = (100*3 + 200*1) / (3+1) = 500/4 = 125
        assert f.vwap == pytest.approx(125.0)


class TestTradeImbalance:
    def test_all_buys_imbalance(self, engine: FeatureEngine):
        # is_buyer_maker=True means maker was buyer (taker sold)
        engine.on_trade(100.0, 1.0, True, 1000)
        engine.on_trade(100.0, 1.0, True, 2000)
        f = engine.compute()
        assert f.trade_imbalance == pytest.approx(1.0)

    def test_all_sells_imbalance(self, engine: FeatureEngine):
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_trade(100.0, 1.0, False, 2000)
        f = engine.compute()
        assert f.trade_imbalance == pytest.approx(-1.0)

    def test_balanced_imbalance(self, engine: FeatureEngine):
        engine.on_trade(100.0, 1.0, True, 1000)
        engine.on_trade(100.0, 1.0, False, 2000)
        f = engine.compute()
        assert f.trade_imbalance == pytest.approx(0.0)


class TestVolatility:
    def test_constant_price_zero_volatility(self, engine: FeatureEngine):
        for i in range(5):
            engine.on_trade(100.0, 1.0, False, i * 1000)
        f = engine.compute()
        assert f.volatility == pytest.approx(0.0)

    def test_varying_price_nonzero_volatility(self, engine: FeatureEngine):
        prices = [100.0, 102.0, 98.0, 101.0, 99.0]
        for i, p in enumerate(prices):
            engine.on_trade(p, 1.0, False, i * 1000)
        f = engine.compute()
        assert f.volatility > 0.0

    def test_single_trade_zero_volatility(self, engine: FeatureEngine):
        engine.on_trade(100.0, 1.0, False, 1000)
        f = engine.compute()
        assert f.volatility == 0.0


class TestTradeRate:
    def test_trade_rate_per_second(self, engine: FeatureEngine):
        # 5 trades over 4 seconds
        for i in range(5):
            engine.on_trade(100.0, 1.0, False, i * 1000)
        f = engine.compute()
        assert f.trade_rate == pytest.approx(5.0 / 4.0)

    def test_single_trade_zero_rate(self, engine: FeatureEngine):
        engine.on_trade(100.0, 1.0, False, 1000)
        f = engine.compute()
        assert f.trade_rate == 0.0


class TestBookSnapshot:
    def test_book_state_passed_through(self, engine: FeatureEngine):
        engine.on_book_snapshot(mid_price=100.5, spread=1.0, imbalance=0.3)
        engine.on_trade(100.0, 1.0, False, 1000)
        f = engine.compute()
        assert f.mid_price == pytest.approx(100.5)
        assert f.spread == pytest.approx(1.0)
        assert f.book_imbalance == pytest.approx(0.3)


class TestWindowEviction:
    def test_old_trades_evicted(self):
        engine = FeatureEngine(symbol="BTCUSD", window_size=3)
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_trade(200.0, 1.0, False, 2000)
        engine.on_trade(300.0, 1.0, False, 3000)
        # Window is full. Adding one more should evict the 100.0 trade
        engine.on_trade(400.0, 1.0, False, 4000)
        f = engine.compute()
        # VWAP should be (200+300+400)/3 = 300
        assert f.vwap == pytest.approx(300.0)
