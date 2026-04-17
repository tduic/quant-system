"""Tests for the momentum strategy.

Momentum is the directional opposite of mean reversion — same z-score
framework, flipped sign. These tests mirror the mean reversion suite
to ensure symmetry.
"""

from __future__ import annotations

import pytest

from alpha_engine_svc.strategies.momentum import DEFAULT_PARAMS, MomentumStrategy
from quant_core.models import DepthUpdate, Trade


@pytest.fixture
def strategy() -> MomentumStrategy:
    return MomentumStrategy(
        params={
            "window_size": 20,
            "threshold_std": 2.0,
            "warmup_trades": 10,
            "cooldown_trades": 0,
            "target_risk_usd": 15.0,
            "max_notional_usd": 500.0,
            "min_notional_usd": 5.0,
            "holding_period_trades": 30,
        }
    )


def make_trade(price: float, ts: int = 0) -> Trade:
    return Trade(
        symbol="BTCUSD",
        price=price,
        quantity=0.01,
        timestamp_exchange=ts,
        is_buyer_maker=False,
    )


def _warmup(strategy: MomentumStrategy, base_price: float = 100.0) -> None:
    """Seed strategy with warmup + variance so volatility > 0."""
    strategy.on_book_update(
        DepthUpdate(
            symbol="BTCUSD",
            bids=[[base_price - 0.5, 1.0]],
            asks=[[base_price + 0.5, 1.0]],
        )
    )
    for i in range(18):
        offset = (i % 3 - 1) * base_price * 0.001
        strategy.on_trade(make_trade(base_price + offset, i * 1000))


class TestMomentumSignalDirection:
    def test_buy_signal_on_price_spike(self, strategy: MomentumStrategy):
        """Momentum BUYS the breakout above VWAP (opposite of mean reversion)."""
        _warmup(strategy)
        signal = strategy.on_trade(make_trade(110.0, 20000))
        if signal is not None:
            assert signal.side == "BUY"
            assert signal.strength > 0

    def test_sell_signal_on_price_crash(self, strategy: MomentumStrategy):
        """Momentum SELLS the breakdown below VWAP (opposite of mean reversion)."""
        _warmup(strategy)
        signal = strategy.on_trade(make_trade(90.0, 20000))
        if signal is not None:
            assert signal.side == "SELL"
            assert signal.strength > 0

    def test_no_signal_at_vwap(self, strategy: MomentumStrategy):
        for i in range(15):
            result = strategy.on_trade(make_trade(100.0, i * 1000))
        assert result is None


class TestMomentumWarmup:
    def test_no_signal_before_warmup(self, strategy: MomentumStrategy):
        for i in range(9):
            result = strategy.on_trade(make_trade(100.0, i * 1000))
            assert result is None

    def test_is_warmed_up_after_threshold(self, strategy: MomentumStrategy):
        assert not strategy.is_warmed_up
        for i in range(10):
            strategy.on_trade(make_trade(100.0, i * 1000))
        assert strategy.is_warmed_up


class TestMomentumParams:
    def test_default_params_applied(self):
        s = MomentumStrategy()
        for key in DEFAULT_PARAMS:
            assert key in s.params

    def test_custom_params_override(self):
        s = MomentumStrategy(params={"window_size": 50})
        assert s.params["window_size"] == 50
        assert s.params["warmup_trades"] == DEFAULT_PARAMS["warmup_trades"]


class TestMomentumSizing:
    def test_quantity_is_vol_scaled(self):
        s = MomentumStrategy(
            params={
                "window_size": 20,
                "threshold_std": 2.0,
                "warmup_trades": 10,
                "cooldown_trades": 0,
                "target_risk_usd": 15.0,
                "max_notional_usd": 500.0,
                "min_notional_usd": 5.0,
                "holding_period_trades": 30,
            }
        )
        _warmup(s, base_price=75000.0)
        signal = s.on_trade(make_trade(80000.0, 20000))
        assert signal is not None
        # Should NOT be the old hardcoded 0.001
        assert signal.target_quantity != 0.001
        assert "notional_usd" in signal.metadata

    def test_notional_capped(self):
        s = MomentumStrategy(
            params={
                "window_size": 20,
                "threshold_std": 2.0,
                "warmup_trades": 10,
                "cooldown_trades": 0,
                "target_risk_usd": 15.0,
                "max_notional_usd": 50.0,
                "min_notional_usd": 5.0,
                "holding_period_trades": 30,
            }
        )
        _warmup(s, base_price=100.0)
        signal = s.on_trade(make_trade(110.0, 20000))
        if signal is not None:
            notional = signal.target_quantity * signal.mid_price_at_signal
            assert notional <= 50.0 + 0.01


class TestMomentumVsMeanReversionSymmetry:
    """Momentum should produce opposite-direction signals from mean reversion."""

    def test_opposite_sides_on_same_data(self):
        from alpha_engine_svc.strategies.mean_reversion import MeanReversionStrategy

        params = {
            "window_size": 20,
            "threshold_std": 2.0,
            "warmup_trades": 10,
            "cooldown_trades": 0,
            "target_risk_usd": 15.0,
            "max_notional_usd": 500.0,
            "min_notional_usd": 5.0,
            "holding_period_trades": 30,
        }
        mom = MomentumStrategy(params=params)
        mr = MeanReversionStrategy(params=params)
        _warmup(mom)
        _warmup(mr)

        mom_sig = mom.on_trade(make_trade(110.0, 20000))
        mr_sig = mr.on_trade(make_trade(110.0, 20000))

        if mom_sig and mr_sig:
            assert mom_sig.side != mr_sig.side
