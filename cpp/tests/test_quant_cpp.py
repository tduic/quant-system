"""Python tests for the quant_cpp C++ module.

These tests verify that the pybind11 bindings produce identical results
to the Python implementations. They are skipped if quant_cpp is not built.
"""

from __future__ import annotations

import pytest

try:
    import quant_cpp

    HAS_CPP = True
except ImportError:
    HAS_CPP = False

pytestmark = pytest.mark.skipif(not HAS_CPP, reason="quant_cpp not built")


# ── OrderBook ────────────────────────────────────────────────────────────


class TestCppOrderBook:
    def test_empty_book(self):
        book = quant_cpp.OrderBook("BTCUSD")
        assert book.symbol == "BTCUSD"
        assert book.best_bid() is None
        assert book.best_ask() is None
        assert book.mid_price() is None
        assert book.spread() is None

    def test_apply_delta_and_best_bid(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([(100.0, 1.0), (99.0, 2.0)], [])
        bid = book.best_bid()
        assert bid is not None
        assert bid[0] == pytest.approx(100.0)
        assert bid[1] == pytest.approx(1.0)

    def test_apply_delta_and_best_ask(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([], [(101.0, 1.5), (102.0, 3.0)])
        ask = book.best_ask()
        assert ask is not None
        assert ask[0] == pytest.approx(101.0)

    def test_mid_price_and_spread(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([(100.0, 1.0)], [(102.0, 1.0)])
        assert book.mid_price() == pytest.approx(101.0)
        assert book.spread() == pytest.approx(2.0)

    def test_remove_level(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([(100.0, 1.0), (99.0, 2.0)], [])
        assert book.bid_count == 2
        book.apply_delta([(100.0, 0.0)], [])
        assert book.bid_count == 1
        assert book.best_bid()[0] == pytest.approx(99.0)

    def test_imbalance(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([(100.0, 3.0)], [(101.0, 1.0)])
        assert book.imbalance() == pytest.approx(0.5)

    def test_top_bids_sorted(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([(98.0, 1.0), (100.0, 2.0), (99.0, 3.0)], [])
        bids = book.top_bids(2)
        assert len(bids) == 2
        assert bids[0][0] == pytest.approx(100.0)
        assert bids[1][0] == pytest.approx(99.0)

    def test_top_asks_sorted(self):
        book = quant_cpp.OrderBook("BTCUSD")
        book.apply_delta([], [(103.0, 1.0), (101.0, 2.0), (102.0, 3.0)])
        asks = book.top_asks(2)
        assert len(asks) == 2
        assert asks[0][0] == pytest.approx(101.0)
        assert asks[1][0] == pytest.approx(102.0)


# ── FeatureEngine ────────────────────────────────────────────────────────


class TestCppFeatureEngine:
    def test_empty_engine(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        assert engine.symbol == "BTCUSD"
        assert engine.count == 0
        f = engine.compute()
        assert f.vwap == pytest.approx(0.0)

    def test_vwap(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_trade(200.0, 3.0, True, 2000)
        f = engine.compute()
        assert f.vwap == pytest.approx(175.0)

    def test_trade_imbalance(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        engine.on_trade(100.0, 3.0, True, 1000)
        engine.on_trade(100.0, 1.0, False, 2000)
        f = engine.compute()
        assert f.trade_imbalance == pytest.approx(0.5)

    def test_volatility_positive(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_trade(110.0, 1.0, False, 2000)
        engine.on_trade(100.0, 1.0, False, 3000)
        f = engine.compute()
        assert f.volatility > 0.0

    def test_trade_rate(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        for i in range(5):
            engine.on_trade(100.0, 1.0, False, i * 1000)
        f = engine.compute()
        assert f.trade_rate == pytest.approx(1.25)

    def test_window_eviction(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 3)
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_trade(200.0, 1.0, False, 2000)
        engine.on_trade(300.0, 1.0, False, 3000)
        engine.on_trade(400.0, 1.0, False, 4000)
        assert engine.count == 3
        f = engine.compute()
        assert f.vwap == pytest.approx(300.0)

    def test_book_snapshot(self):
        engine = quant_cpp.FeatureEngine("BTCUSD", 100)
        engine.on_trade(100.0, 1.0, False, 1000)
        engine.on_book_snapshot(100.5, 1.0, 0.3)
        f = engine.compute()
        assert f.mid_price == pytest.approx(100.5)
        assert f.spread == pytest.approx(1.0)
        assert f.book_imbalance == pytest.approx(0.3)


# ── MatchingEngine ───────────────────────────────────────────────────────


class TestCppMatchingEngine:
    def test_simple_buy(self):
        engine = quant_cpp.MatchingEngine(0.006, 50.0, False)
        result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0)
        assert result.fill_price == pytest.approx(101.0)
        assert result.fee == pytest.approx(1.0 * 101.0 * 0.006)

    def test_simple_sell(self):
        engine = quant_cpp.MatchingEngine(0.006, 50.0, False)
        result = engine.simulate_fill("SELL", 1.0, 100.0, 2.0)
        assert result.fill_price == pytest.approx(99.0)

    def test_slippage_bps(self):
        engine = quant_cpp.MatchingEngine(0.006, 50.0, False)
        result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0)
        assert result.slippage_bps == pytest.approx(100.0)

    def test_walk_the_book(self):
        price = quant_cpp.MatchingEngine.walk_the_book(
            3.0, [(101.0, 2.0), (102.0, 5.0)]
        )
        assert price == pytest.approx(304.0 / 3.0)

    def test_fill_with_book_depth(self):
        engine = quant_cpp.MatchingEngine(0.006, 50.0, False)
        depth = [(101.0, 2.0), (102.0, 5.0)]
        result = engine.simulate_fill("BUY", 3.0, 100.0, 2.0, depth)
        assert result.fill_price == pytest.approx(304.0 / 3.0)

    def test_brownian_bridge_deterministic(self):
        e1 = quant_cpp.MatchingEngine(0.006, 50.0, True, 42)
        e1.set_volatility(0.5)
        r1 = e1.simulate_fill("BUY", 1.0, 100.0, 2.0)

        e2 = quant_cpp.MatchingEngine(0.006, 50.0, True, 42)
        e2.set_volatility(0.5)
        r2 = e2.simulate_fill("BUY", 1.0, 100.0, 2.0)

        assert r1.fill_price == pytest.approx(r2.fill_price)

    def test_zero_vol_fallback(self):
        engine = quant_cpp.MatchingEngine(0.006, 50.0, True, 42)
        result = engine.simulate_fill("BUY", 1.0, 100.0, 2.0)
        assert result.fill_price == pytest.approx(101.0)
