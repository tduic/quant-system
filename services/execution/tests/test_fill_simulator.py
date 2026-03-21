"""Tests for execution_svc.fill_simulator — paper trading fills."""

from __future__ import annotations

import pytest

from execution_svc.fill_simulator import DEFAULT_FEE_RATE, FillSimulator
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


class TestFillPrice:
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
