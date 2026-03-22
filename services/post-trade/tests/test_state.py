"""Tests for post_trade_svc.state — in-memory analytics state."""

from __future__ import annotations

import pytest

from post_trade_svc.state import FillRecord, PostTradeState


@pytest.fixture
def state() -> PostTradeState:
    return PostTradeState(initial_equity=100_000.0)


def make_fill(
    fill_id: str = "f1",
    symbol: str = "BTCUSD",
    side: str = "BUY",
    quantity: float = 0.001,
    fill_price: float = 80_000.0,
    fee: float = 0.48,
    slippage_bps: float = 0.12,
    strategy_id: str = "test",
    timestamp: int = 1000,
) -> FillRecord:
    return FillRecord(
        fill_id=fill_id,
        timestamp=timestamp,
        symbol=symbol,
        side=side,
        quantity=quantity,
        fill_price=fill_price,
        fee=fee,
        slippage_bps=slippage_bps,
        strategy_id=strategy_id,
    )


class TestProcessFill:
    def test_single_fill_updates_pnl(self, state: PostTradeState):
        state.process_fill(make_fill())
        pnl = state.get_pnl_summary()
        assert pnl["num_fills"] == 1
        assert "BTCUSD" in pnl["positions"]

    def test_buy_then_sell_realizes_pnl(self, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        state.process_fill(make_fill(fill_id="f1", side="BUY", fill_price=80_000.0, timestamp=1000))
        state.update_price("BTCUSD", 81_000.0)
        state.process_fill(make_fill(fill_id="f2", side="SELL", fill_price=81_000.0, timestamp=2000))

        pnl = state.get_pnl_summary()
        assert pnl["total_realized_pnl"] > 0

    def test_equity_curve_grows(self, state: PostTradeState):
        state.process_fill(make_fill(fill_id="f1", timestamp=1000))
        state.process_fill(make_fill(fill_id="f2", timestamp=2000))
        dd = state.get_drawdown_data()
        assert len(dd["equity_curve"]) == 2

    def test_tca_recorded(self, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        state.process_fill(make_fill())
        tca = state.get_tca_summary()
        assert tca["num_fills"] == 1
        assert len(tca["fills"]) == 1


class TestUpdatePrice:
    def test_price_updates_reflected_in_pnl(self, state: PostTradeState):
        state.process_fill(make_fill(side="BUY", fill_price=80_000.0))
        state.update_price("BTCUSD", 82_000.0)
        pnl = state.get_pnl_summary()
        assert pnl["total_unrealized_pnl"] > 0


class TestPnLSummary:
    def test_empty_state(self, state: PostTradeState):
        pnl = state.get_pnl_summary()
        assert pnl["initial_equity"] == 100_000.0
        assert pnl["current_equity"] == 100_000.0
        assert pnl["num_fills"] == 0
        assert pnl["positions"] == {}

    def test_return_pct(self, state: PostTradeState):
        pnl = state.get_pnl_summary()
        assert pnl["total_return_pct"] == pytest.approx(0.0)


class TestTCASummary:
    def test_empty_tca(self, state: PostTradeState):
        tca = state.get_tca_summary()
        assert tca["fills"] == []

    def test_averages_computed(self, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        state.process_fill(make_fill(fill_id="f1", fee=0.48))
        state.process_fill(make_fill(fill_id="f2", fee=0.96))
        tca = state.get_tca_summary()
        assert tca["num_fills"] == 2
        assert "averages" in tca


class TestRiskMetrics:
    def test_empty_metrics(self, state: PostTradeState):
        metrics = state.get_risk_metrics()
        assert metrics["num_trades"] == 0
        assert metrics["sharpe_ratio"] == 0.0

    def test_metrics_after_fills(self, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        for i in range(5):
            state.process_fill(
                make_fill(
                    fill_id=f"f{i}",
                    side="BUY" if i % 2 == 0 else "SELL",
                    fill_price=80_000.0 + i * 100,
                    timestamp=i * 1000,
                )
            )
        metrics = state.get_risk_metrics()
        assert metrics["num_trades"] == 5


class TestDrawdownData:
    def test_empty_drawdown(self, state: PostTradeState):
        dd = state.get_drawdown_data()
        assert dd["equity_curve"] == []
        assert dd["current_drawdown_pct"] == 0.0

    def test_drawdown_curve_populated(self, state: PostTradeState):
        state.update_price("BTCUSD", 80_000.0)
        for i in range(3):
            state.process_fill(make_fill(fill_id=f"f{i}", timestamp=i * 1000))
        dd = state.get_drawdown_data()
        assert len(dd["drawdown_curve"]) == 3


class TestFillAnalysis:
    def test_empty_fills(self, state: PostTradeState):
        fills = state.get_fill_analysis()
        assert fills["fills"] == []

    def test_fill_details(self, state: PostTradeState):
        state.process_fill(make_fill(side="BUY"))
        state.process_fill(make_fill(fill_id="f2", side="SELL"))
        fills = state.get_fill_analysis()
        assert fills["summary"]["total_fills"] == 2
        assert fills["summary"]["buy_fills"] == 1
        assert fills["summary"]["sell_fills"] == 1


class TestExcelExport:
    def test_export_returns_all_keys(self, state: PostTradeState):
        data = state.get_all_data_for_export()
        assert "pnl" in data
        assert "tca" in data
        assert "alpha_decay" in data
        assert "risk_metrics" in data
        assert "drawdown" in data
        assert "fills" in data
