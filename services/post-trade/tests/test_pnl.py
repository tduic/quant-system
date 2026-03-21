"""Tests for post_trade_svc.pnl — position tracking and PnL computation."""

from __future__ import annotations

import pytest

from post_trade_svc.pnl import Position, PortfolioPnL


class TestPositionApplyFill:
    def test_open_long_position(self):
        pos = Position(symbol="BTCUSD")
        realized = pos.apply_fill(quantity=1.0, price=100.0, fee=0.1, side="BUY")
        assert realized == 0.0
        assert pos.quantity == pytest.approx(1.0)
        assert pos.avg_entry_price == pytest.approx(100.0)

    def test_add_to_long_position(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.0, "BUY")
        pos.apply_fill(1.0, 110.0, 0.0, "BUY")
        assert pos.quantity == pytest.approx(2.0)
        assert pos.avg_entry_price == pytest.approx(105.0)

    def test_close_long_position_profit(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.0, "BUY")
        realized = pos.apply_fill(1.0, 110.0, 0.0, "SELL")
        assert realized == pytest.approx(10.0)
        assert pos.quantity == pytest.approx(0.0)

    def test_close_long_position_loss(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.0, "BUY")
        realized = pos.apply_fill(1.0, 90.0, 0.0, "SELL")
        assert realized == pytest.approx(-10.0)

    def test_partial_close(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(2.0, 100.0, 0.0, "BUY")
        realized = pos.apply_fill(1.0, 110.0, 0.0, "SELL")
        assert realized == pytest.approx(10.0)
        assert pos.quantity == pytest.approx(1.0)
        assert pos.avg_entry_price == pytest.approx(100.0)  # unchanged

    def test_open_short_position(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.0, "SELL")
        assert pos.quantity == pytest.approx(-1.0)

    def test_close_short_position_profit(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.0, "SELL")
        realized = pos.apply_fill(1.0, 90.0, 0.0, "BUY")
        assert realized == pytest.approx(10.0)

    def test_fees_accumulated(self):
        pos = Position(symbol="BTCUSD")
        pos.apply_fill(1.0, 100.0, 0.5, "BUY")
        pos.apply_fill(1.0, 110.0, 0.3, "SELL")
        assert pos.total_fees == pytest.approx(0.8)


class TestPositionUnrealizedPnL:
    def test_long_profit(self):
        pos = Position(symbol="BTCUSD", quantity=1.0, avg_entry_price=100.0)
        assert pos.unrealized_pnl(110.0) == pytest.approx(10.0)

    def test_long_loss(self):
        pos = Position(symbol="BTCUSD", quantity=1.0, avg_entry_price=100.0)
        assert pos.unrealized_pnl(90.0) == pytest.approx(-10.0)

    def test_short_profit(self):
        pos = Position(symbol="BTCUSD", quantity=-1.0, avg_entry_price=100.0)
        assert pos.unrealized_pnl(90.0) == pytest.approx(10.0)

    def test_flat_position(self):
        pos = Position(symbol="BTCUSD", quantity=0.0, avg_entry_price=100.0)
        assert pos.unrealized_pnl(110.0) == 0.0


class TestPortfolioPnL:
    def test_get_or_create(self):
        pf = PortfolioPnL()
        pos = pf.get_or_create("BTCUSD")
        assert pos.symbol == "BTCUSD"
        assert pf.get_or_create("BTCUSD") is pos  # same object

    def test_total_realized_pnl(self):
        pf = PortfolioPnL()
        p1 = pf.get_or_create("BTCUSD")
        p1.realized_pnl = 50.0
        p2 = pf.get_or_create("ETHUSD")
        p2.realized_pnl = -20.0
        assert pf.total_realized_pnl == pytest.approx(30.0)

    def test_total_fees(self):
        pf = PortfolioPnL()
        p1 = pf.get_or_create("BTCUSD")
        p1.total_fees = 5.0
        p2 = pf.get_or_create("ETHUSD")
        p2.total_fees = 3.0
        assert pf.total_fees == pytest.approx(8.0)

    def test_total_unrealized_pnl(self):
        pf = PortfolioPnL()
        p1 = pf.get_or_create("BTCUSD")
        p1.quantity = 1.0
        p1.avg_entry_price = 80_000.0
        p2 = pf.get_or_create("ETHUSD")
        p2.quantity = -10.0
        p2.avg_entry_price = 3_000.0

        prices = {"BTCUSD": 82_000.0, "ETHUSD": 2_800.0}
        unrealized = pf.total_unrealized_pnl(prices)
        # BTC: 1.0 * (82000-80000) = 2000
        # ETH: 10.0 * (3000-2800) = 2000
        assert unrealized == pytest.approx(4_000.0)
