"""Tests for execution_svc.fill_simulator — paper trading fills."""

from __future__ import annotations

import pytest

from execution_svc.fill_simulator import (
    DEFAULT_FEE_RATE,
    FillSimulator,
    brownian_bridge_sample,
    walk_the_book,
)
from quant_core.models import Order


@pytest.fixture
def sim() -> FillSimulator:
    return FillSimulator()


@pytest.fixture
def buy_order() -> Order:
    return Order(
        symbol="BTCUSD",
        side="BUY",
        quantity=0.1,
        strategy_id="test",
    )


@pytest.fixture
def sell_order() -> Order:
    return Order(
        symbol="BTCUSD",
        side="SELL",
        quantity=0.1,
        strategy_id="test",
    )


# -----------------------------------------------------------------------
# Simple fill tests (Phase 2 — no brownian bridge)
# -----------------------------------------------------------------------


class TestSimpleFillPrice:
    def test_buy_fills_above_mid(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.fill_price == pytest.approx(80_001.0)

    def test_sell_fills_below_mid(self, sim: FillSimulator, sell_order: Order):
        fill = sim.simulate_fill(sell_order, mid_price=80_000.0, spread=2.0)
        assert fill.fill_price == pytest.approx(79_999.0)

    def test_zero_spread_fills_at_mid(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=0.0)
        assert fill.fill_price == pytest.approx(80_000.0)


class TestSlippage:
    def test_slippage_is_half_spread_in_bps(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        expected_bps = 1.0 / 80_000.0 * 10_000
        assert fill.slippage_bps == pytest.approx(expected_bps)

    def test_zero_spread_zero_slippage(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=0.0)
        assert fill.slippage_bps == pytest.approx(0.0)


class TestFees:
    def test_default_fee_rate(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        expected_fee = 0.1 * 80_001.0 * DEFAULT_FEE_RATE
        assert fill.fee == pytest.approx(expected_fee)

    def test_custom_fee_rate(self, buy_order: Order):
        sim = FillSimulator(fee_rate=0.001)
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=0.0)
        assert fill.fee == pytest.approx(0.1 * 80_000.0 * 0.001)

    def test_zero_fee_rate(self, buy_order: Order):
        sim = FillSimulator(fee_rate=0.0)
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=0.0)
        assert fill.fee == pytest.approx(0.0)


class TestFillMetadata:
    def test_order_id_propagated(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.order_id == buy_order.order_id

    def test_symbol_propagated(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.symbol == "BTCUSD"

    def test_side_propagated(self, sim: FillSimulator, sell_order: Order):
        fill = sim.simulate_fill(sell_order, mid_price=80_000.0, spread=2.0)
        assert fill.side == "SELL"

    def test_quantity_propagated(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.quantity == pytest.approx(0.1)

    def test_strategy_id_propagated(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.strategy_id == "test"

    def test_backtest_id_propagated(self, sim: FillSimulator, buy_order: Order):
        buy_order.backtest_id = "bt-123"
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.backtest_id == "bt-123"

    def test_timestamp_set(self, sim: FillSimulator, buy_order: Order):
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.timestamp > 0

    def test_fill_id_is_unique(self, sim: FillSimulator, buy_order: Order):
        f1 = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        f2 = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert f1.fill_id != f2.fill_id


# -----------------------------------------------------------------------
# Walk-the-book tests
# -----------------------------------------------------------------------


class TestWalkTheBook:
    def test_single_level_full_fill(self):
        book = [(100.0, 1.0)]
        assert walk_the_book(0.5, book) == pytest.approx(100.0)

    def test_multiple_levels(self):
        book = [(100.0, 0.5), (101.0, 0.5), (102.0, 1.0)]
        # Fill 0.8: 0.5 @ 100 + 0.3 @ 101 = 50 + 30.3 = 80.3 / 0.8 = 100.375
        price = walk_the_book(0.8, book)
        assert price == pytest.approx(100.375)

    def test_insufficient_depth(self):
        book = [(100.0, 0.1)]
        # Can only fill 0.1 of 1.0 — returns avg of what was filled
        price = walk_the_book(1.0, book)
        assert price == pytest.approx(100.0)

    def test_empty_book(self):
        assert walk_the_book(1.0, []) == 0.0

    def test_exact_fill_at_level(self):
        book = [(100.0, 1.0), (101.0, 1.0)]
        assert walk_the_book(1.0, book) == pytest.approx(100.0)


# -----------------------------------------------------------------------
# Brownian bridge tests
# -----------------------------------------------------------------------


class TestBrownianBridge:
    def test_zero_volatility_returns_midpoint(self):
        price = brownian_bridge_sample(100.0, 110.0, 0.0, 1.0)
        assert price == pytest.approx(105.0)

    def test_zero_dt_returns_midpoint(self):
        price = brownian_bridge_sample(100.0, 110.0, 1.0, 0.0)
        assert price == pytest.approx(105.0)

    def test_bridge_is_between_endpoints_on_average(self):
        # Statistical test: average of many samples should be near midpoint
        samples = []
        for _ in range(10000):
            s = brownian_bridge_sample(100.0, 110.0, 0.5, 0.05)
            samples.append(s)
        mean = sum(samples) / len(samples)
        assert mean == pytest.approx(105.0, abs=0.5)

    def test_higher_vol_wider_distribution(self):
        low_vol_samples = [brownian_bridge_sample(100.0, 100.0, 0.01, 1.0) for _ in range(1000)]
        high_vol_samples = [brownian_bridge_sample(100.0, 100.0, 10.0, 1.0) for _ in range(1000)]

        low_std = _std(low_vol_samples)
        high_std = _std(high_vol_samples)
        assert high_std > low_std


# -----------------------------------------------------------------------
# Brownian bridge simulator integration
# -----------------------------------------------------------------------


class TestBrownianBridgeFill:
    def test_bb_fill_near_simple_fill(self, buy_order: Order):
        """With low volatility, BB fill should be close to simple fill."""
        sim = FillSimulator(use_brownian_bridge=True, fee_rate=0.0)
        sim.set_volatility(0.01)  # very low annualized vol

        fills = []
        for _ in range(100):
            fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
            fills.append(fill.fill_price)

        mean_fill = sum(fills) / len(fills)
        # Should be near 80001 (mid + half spread)
        assert mean_fill == pytest.approx(80_001.0, abs=5.0)

    def test_bb_not_used_without_volatility(self, buy_order: Order):
        sim = FillSimulator(use_brownian_bridge=True, fee_rate=0.0)
        # No set_volatility called — should fall back to simple
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0)
        assert fill.fill_price == pytest.approx(80_001.0)

    def test_bb_with_book_depth(self, buy_order: Order):
        sim = FillSimulator(use_brownian_bridge=True, fee_rate=0.0)
        sim.set_volatility(0.5)
        book = [(80_001.0, 1.0), (80_002.0, 1.0)]
        fill = sim.simulate_fill(buy_order, mid_price=80_000.0, spread=2.0, book_depth=book)
        # Should produce a fill (we're testing it doesn't crash)
        assert fill.fill_price > 0


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5
