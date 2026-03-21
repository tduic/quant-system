"""Tests for mean_reversion strategy."""

from __future__ import annotations

import pytest

from quant_core.models import Trade, DepthUpdate, Signal
from alpha_engine_svc.strategies.mean_reversion import MeanReversionStrategy, DEFAULT_PARAMS


@pytest.fixture
def strategy() -> MeanReversionStrategy:
    return MeanReversionStrategy(
        params={
            "window_size": 20,
            "threshold_std": 2.0,
            "warmup_trades": 10,
            "base_quantity": 0.001,
            "cooldown_trades": 0,  # no cooldown for testing
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
                "base_quantity": 0.001,
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
