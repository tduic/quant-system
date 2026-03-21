"""Tests for post_trade_svc.tca — transaction cost analysis."""

from __future__ import annotations

import pytest

from post_trade_svc.tca import TCAResult, analyze_fill


class TestAnalyzeFillBuy:
    def test_basic_buy_tca(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_010.0,
            fill_price=80_015.0,
            fee=48.0,
            quantity=0.1,
        )
        assert isinstance(result, TCAResult)
        assert result.fill_id == "f1"
        assert result.symbol == "BTCUSD"
        assert result.side == "BUY"

    def test_buy_market_impact_positive_when_price_rises(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_010.0,  # price moved up against us
            fill_price=80_015.0,
            fee=0.0,
            quantity=0.1,
        )
        assert result.market_impact_bps > 0

    def test_buy_slippage_positive_when_fill_above_arrival(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_000.0,
            fill_price=80_010.0,  # filled above arrival
            fee=0.0,
            quantity=0.1,
        )
        assert result.slippage_bps > 0


class TestAnalyzeFillSell:
    def test_sell_market_impact_positive_when_price_drops(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="SELL",
            decision_price=80_000.0,
            arrival_price=79_990.0,  # price moved down against us
            fill_price=79_985.0,
            fee=0.0,
            quantity=0.1,
        )
        assert result.market_impact_bps > 0

    def test_sell_slippage_positive_when_fill_below_arrival(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="SELL",
            decision_price=80_000.0,
            arrival_price=80_000.0,
            fill_price=79_990.0,  # filled below arrival
            fee=0.0,
            quantity=0.1,
        )
        assert result.slippage_bps > 0


class TestFees:
    def test_fee_bps_computed(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_000.0,
            fill_price=80_000.0,
            fee=48.0,
            quantity=0.1,
        )
        # fee_bps = 48 / (0.1 * 80000) * 10000 = 48/8000 * 10000 = 60
        assert result.fee_bps == pytest.approx(60.0)

    def test_zero_fee(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_000.0,
            fill_price=80_000.0,
            fee=0.0,
            quantity=0.1,
        )
        assert result.fee_bps == pytest.approx(0.0)


class TestTotalCost:
    def test_total_cost_sums_components(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_010.0,
            fill_price=80_020.0,
            fee=48.0,
            quantity=0.1,
        )
        assert result.total_cost_bps > 0
        assert result.total_cost_bps >= result.fee_bps

    def test_perfect_execution_only_fee(self):
        result = analyze_fill(
            fill_id="f1",
            symbol="BTCUSD",
            side="BUY",
            decision_price=80_000.0,
            arrival_price=80_000.0,
            fill_price=80_000.0,
            fee=48.0,
            quantity=0.1,
        )
        assert result.total_cost_bps == pytest.approx(result.fee_bps)
