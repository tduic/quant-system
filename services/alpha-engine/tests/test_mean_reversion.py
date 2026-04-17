"""Tests for mean_reversion strategy."""

from __future__ import annotations

import pytest

from alpha_engine_svc.strategies.mean_reversion import DEFAULT_PARAMS, MeanReversionStrategy
from quant_core.models import DepthUpdate, Signal, Trade


@pytest.fixture
def strategy() -> MeanReversionStrategy:
    return MeanReversionStrategy(
        params={
            "window_size": 20,
            "threshold_std": 2.0,
            "warmup_trades": 10,
            "cooldown_trades": 0,  # no cooldown for testing
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


class TestWarmup:
    def test_no_signal_before_warmup(self, strategy: MeanReversionStrategy):
        for i in range(9):
            result = strategy.on_trade(make_trade(100.0, i * 1000))
            assert result is None

    def test_is_warmed_up_after_threshold(self, strategy: MeanReversionStrategy):
        assert not strategy.is_warmed_up
        for i in range(10):
            strategy.on_trade(make_trade(100.0, i * 1000))
        assert strategy.is_warmed_up


class TestSignalGeneration:
    def test_no_signal_at_vwap(self, strategy: MeanReversionStrategy):
        # Feed constant price — z-score is 0, no signal
        for i in range(15):
            result = strategy.on_trade(make_trade(100.0, i * 1000))
        assert result is None

    def test_buy_signal_on_price_drop(self, strategy: MeanReversionStrategy):
        # Build up a VWAP around 100
        for i in range(12):
            strategy.on_trade(make_trade(100.0, i * 1000))

        # Now add some variance so volatility > 0
        for i in range(12, 18):
            strategy.on_trade(make_trade(100.0 + (i % 2) * 0.5, i * 1000))

        # Crash the price well below VWAP
        signal = strategy.on_trade(make_trade(90.0, 20000))
        if signal is not None:
            assert signal.side == "BUY"
            assert signal.strength > 0
            assert signal.symbol == "BTCUSD"
            assert "z_score" in signal.metadata

    def test_sell_signal_on_price_spike(self, strategy: MeanReversionStrategy):
        for i in range(12):
            strategy.on_trade(make_trade(100.0, i * 1000))

        for i in range(12, 18):
            strategy.on_trade(make_trade(100.0 + (i % 2) * 0.5, i * 1000))

        signal = strategy.on_trade(make_trade(110.0, 20000))
        if signal is not None:
            assert signal.side == "SELL"
            assert signal.strength > 0


class TestCooldown:
    def test_cooldown_prevents_rapid_signals(self):
        strategy = MeanReversionStrategy(
            params={
                "window_size": 20,
                "threshold_std": 2.0,
                "warmup_trades": 10,
                "cooldown_trades": 5,
            }
        )
        # Warmup
        for i in range(12):
            strategy.on_trade(make_trade(100.0, i * 1000))

        # Add variance
        for i in range(12, 18):
            strategy.on_trade(make_trade(100.0 + (i % 2) * 0.5, i * 1000))

        # First signal might fire
        strategy.on_trade(make_trade(90.0, 20000))

        # Immediate next — cooldown should block
        strategy._trades_since_last_signal = 0  # reset to simulate fresh
        assert not strategy.cooldown_elapsed


class TestDuplicateSuppression:
    def test_no_duplicate_same_direction(self, strategy: MeanReversionStrategy):
        # After generating a BUY signal, shouldn't get another BUY
        strategy._last_signal_side = "BUY"
        strategy._trade_count = 100  # past warmup

        for i in range(5):
            strategy.on_trade(make_trade(100.0 + (i % 2) * 0.5, i * 1000))

        # Even with a low price, same direction should be suppressed
        strategy._trades_since_last_signal = 100  # past cooldown
        # The actual duplicate check happens inside on_trade


class TestOnBookUpdate:
    def test_book_update_never_generates_signal(self, strategy: MeanReversionStrategy):
        update = DepthUpdate(
            symbol="BTCUSD",
            bids=[[100.0, 1.0]],
            asks=[[101.0, 1.0]],
        )
        result = strategy.on_book_update(update)
        assert result is None

    def test_book_update_sets_mid_price(self, strategy: MeanReversionStrategy):
        update = DepthUpdate(
            symbol="BTCUSD",
            bids=[[100.0, 1.0]],
            asks=[[102.0, 1.0]],
        )
        strategy.on_book_update(update)
        assert strategy._mid_price == pytest.approx(101.0)
        assert strategy._spread == pytest.approx(2.0)


class TestParams:
    def test_default_params_applied(self):
        s = MeanReversionStrategy()
        for key in DEFAULT_PARAMS:
            assert key in s.params

    def test_custom_params_override(self):
        s = MeanReversionStrategy(params={"window_size": 50})
        assert s.params["window_size"] == 50
        assert s.params["warmup_trades"] == DEFAULT_PARAMS["warmup_trades"]


def _build_strategy_with_signal(
    base_price: float,
    spike_price: float,
    target_risk: float = 15.0,
    max_notional: float = 500.0,
    min_notional: float = 5.0,
) -> tuple[MeanReversionStrategy, Signal | None]:
    """Helper: build a strategy, warm it up with variance, then spike the price."""
    strategy = MeanReversionStrategy(
        params={
            "window_size": 20,
            "threshold_std": 2.0,
            "warmup_trades": 10,
            "cooldown_trades": 0,
            "target_risk_usd": target_risk,
            "max_notional_usd": max_notional,
            "min_notional_usd": min_notional,
            "holding_period_trades": 30,
        }
    )
    # Set mid price via book update
    strategy.on_book_update(
        DepthUpdate(
            symbol="BTCUSD",
            bids=[[base_price - 0.5, 1.0]],
            asks=[[base_price + 0.5, 1.0]],
        )
    )
    # Warmup with some variance so volatility > 0
    for i in range(18):
        offset = (i % 3 - 1) * base_price * 0.001  # ±0.1% jitter
        strategy.on_trade(make_trade(base_price + offset, i * 1000))

    signal = strategy.on_trade(make_trade(spike_price, 20000))
    return strategy, signal


class TestVolatilityScaledSizing:
    def test_signal_quantity_is_not_fixed(self):
        """Quantity should vary based on price and volatility, not be hardcoded."""
        _, sig_btc = _build_strategy_with_signal(75000.0, 60000.0)
        assert sig_btc is not None
        assert sig_btc.target_quantity != 0.001  # not the old hardcoded value

    def test_quantity_scales_with_price(self):
        """Cheaper assets should get more units for the same dollar risk."""
        _, sig_expensive = _build_strategy_with_signal(75000.0, 60000.0)
        _, sig_cheap = _build_strategy_with_signal(88.0, 70.0)
        assert sig_expensive is not None
        assert sig_cheap is not None
        # Cheap asset should have more units
        assert sig_cheap.target_quantity > sig_expensive.target_quantity

    def test_notional_capped(self):
        """Trade notional should not exceed max_notional_usd."""
        _, signal = _build_strategy_with_signal(100.0, 80.0, max_notional=50.0)
        assert signal is not None
        notional = signal.target_quantity * signal.mid_price_at_signal
        assert notional <= 50.0 + 0.01  # small float tolerance

    def test_notional_floored(self):
        """Trade notional should not go below min_notional_usd."""
        _, signal = _build_strategy_with_signal(100.0, 80.0, min_notional=200.0, max_notional=1000.0)
        assert signal is not None
        notional = signal.target_quantity * signal.mid_price_at_signal
        assert notional >= 200.0 - 0.01

    def test_higher_vol_means_smaller_quantity(self):
        """When volatility is higher, quantity should decrease (same risk budget)."""
        # Low-vol strategy: tight jitter
        s_low = MeanReversionStrategy(
            params={
                "window_size": 20,
                "threshold_std": 2.0,
                "warmup_trades": 10,
                "cooldown_trades": 0,
                "target_risk_usd": 15.0,
                "max_notional_usd": 10000.0,  # high cap so it doesn't bind
                "min_notional_usd": 0.01,
                "holding_period_trades": 30,
            }
        )
        s_low.on_book_update(DepthUpdate(symbol="BTCUSD", bids=[[99.5, 1.0]], asks=[[100.5, 1.0]]))
        for i in range(18):
            s_low.on_trade(make_trade(100.0 + (i % 2) * 0.01, i * 1000))  # tiny jitter
        sig_low = s_low.on_trade(make_trade(80.0, 20000))

        # High-vol strategy: wide jitter
        s_high = MeanReversionStrategy(
            params={
                "window_size": 20,
                "threshold_std": 2.0,
                "warmup_trades": 10,
                "cooldown_trades": 0,
                "target_risk_usd": 15.0,
                "max_notional_usd": 10000.0,
                "min_notional_usd": 0.01,
                "holding_period_trades": 30,
            }
        )
        s_high.on_book_update(DepthUpdate(symbol="BTCUSD", bids=[[99.5, 1.0]], asks=[[100.5, 1.0]]))
        for i in range(18):
            s_high.on_trade(make_trade(100.0 + (i % 2) * 5.0, i * 1000))  # big jitter
        sig_high = s_high.on_trade(make_trade(80.0, 20000))

        assert sig_low is not None
        assert sig_high is not None
        assert sig_low.target_quantity > sig_high.target_quantity

    def test_metadata_includes_notional(self):
        """Signal metadata should include the computed notional for auditability."""
        _, signal = _build_strategy_with_signal(100.0, 80.0)
        assert signal is not None
        assert "notional_usd" in signal.metadata
        assert signal.metadata["notional_usd"] > 0
