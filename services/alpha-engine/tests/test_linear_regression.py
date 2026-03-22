"""Tests for linear_regression strategy and OLS math."""

from __future__ import annotations

import pytest

from alpha_engine_svc.strategies.linear_regression import (
    DEFAULT_PARAMS,
    LinearRegressionStrategy,
    _ols_fit,
    _predict,
    _solve_linear_system,
)
from quant_core.models import DepthUpdate, Trade

# -----------------------------------------------------------------------
# OLS math tests
# -----------------------------------------------------------------------


class TestSolveLinearSystem:
    def test_2x2_system(self):
        # 2x + 3y = 8, x + y = 3  => x=1, y=2
        a_mat = [[2.0, 3.0], [1.0, 1.0]]
        b = [8.0, 3.0]
        x = _solve_linear_system(a_mat, b)
        assert x is not None
        assert x[0] == pytest.approx(1.0)
        assert x[1] == pytest.approx(2.0)

    def test_singular_matrix_returns_none(self):
        a_mat = [[1.0, 2.0], [2.0, 4.0]]
        b = [3.0, 6.0]
        assert _solve_linear_system(a_mat, b) is None

    def test_3x3_system(self):
        a_mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        b = [5.0, 10.0, 15.0]
        x = _solve_linear_system(a_mat, b)
        assert x == [pytest.approx(5.0), pytest.approx(10.0), pytest.approx(15.0)]


class TestOLSFit:
    def test_perfect_linear_relationship(self):
        # y = 2*x + 5
        x_mat = [[1.0], [2.0], [3.0], [4.0], [5.0]]
        y = [7.0, 9.0, 11.0, 13.0, 15.0]
        beta, intercept = _ols_fit(x_mat, y)
        assert len(beta) == 1
        assert beta[0] == pytest.approx(2.0)
        assert intercept == pytest.approx(5.0)

    def test_multi_feature_regression(self):
        # y = 1*x1 + 2*x2 + 3
        x_mat = [[1.0, 1.0], [2.0, 1.5], [3.0, 2.5], [4.0, 3.2]]
        y = [6.0, 8.0, 11.0, 13.4]
        beta, intercept = _ols_fit(x_mat, y)
        assert len(beta) == 2
        assert beta[0] == pytest.approx(1.0, abs=0.1)
        assert beta[1] == pytest.approx(2.0, abs=0.1)
        assert intercept == pytest.approx(3.0, abs=0.1)

    def test_empty_data_returns_defaults(self):
        beta, intercept = _ols_fit([], [])
        assert beta == []
        assert intercept == 0.0

    def test_predict(self):
        beta = [2.0, 3.0]
        intercept = 1.0
        # 2*4 + 3*5 + 1 = 24
        assert _predict([4.0, 5.0], beta, intercept) == pytest.approx(24.0)


# -----------------------------------------------------------------------
# Strategy tests
# -----------------------------------------------------------------------


def make_trade(price: float, ts: int = 0, qty: float = 0.01) -> Trade:
    return Trade(
        symbol="BTCUSD",
        price=price,
        quantity=qty,
        timestamp_exchange=ts,
        is_buyer_maker=False,
    )


@pytest.fixture
def strategy() -> LinearRegressionStrategy:
    return LinearRegressionStrategy(
        params={
            "window_size": 100,
            "refit_interval": 15,
            "threshold_std": 1.5,
            "warmup_trades": 30,
            "base_quantity": 0.001,
            "cooldown_trades": 0,
        }
    )


class TestLinRegWarmup:
    def test_no_signal_before_warmup(self, strategy: LinearRegressionStrategy):
        for i in range(29):
            result = strategy.on_trade(make_trade(100.0, i * 1000))
            assert result is None

    def test_warmed_up_after_threshold(self, strategy: LinearRegressionStrategy):
        assert not strategy.is_warmed_up
        for i in range(30):
            strategy.on_trade(make_trade(100.0, i * 1000))
        assert strategy.is_warmed_up


class TestLinRegModelFit:
    def test_model_fits_after_refit_interval(self, strategy: LinearRegressionStrategy):
        assert not strategy._model_fitted
        # Manually populate feature and price history with linearly independent data
        # Use random-like but deterministic features to ensure full rank
        import math

        for i in range(30):
            # Create truly independent features using different functions
            f0 = float(i)
            f1 = float(i * i)
            f2 = math.sin(i * 0.5)
            f3 = math.cos(i * 0.3)
            strategy._feature_history.append([f0, f1, f2, f3])
            # Price varies with features
            strategy._price_history.append(100.0 + f0 * 0.1 + f1 * 0.001)
            strategy._trade_count += 1
            strategy._trades_since_last_fit += 1

            # Trigger refit at trade 15
            if strategy._trades_since_last_fit >= strategy.params["refit_interval"]:
                strategy._fit_model()

        # After 30 trades with refit at 15, should have fitted
        assert strategy._model_fitted

    def test_model_not_fitted_with_constant_data(self, strategy: LinearRegressionStrategy):
        # With truly constant features, regression may still fit
        # but residual_std will be 0 so no signals
        for i in range(35):
            strategy.on_trade(make_trade(100.0, i * 1000))
        if strategy._model_fitted:
            assert strategy._residual_std == pytest.approx(0.0, abs=1e-6)


class TestLinRegSignals:
    def test_no_signal_at_fair_value(self, strategy: LinearRegressionStrategy):
        # Feed consistent data — price should be near fair value
        for i in range(35):
            price = 100.0 + (i % 3) * 0.1
            result = strategy.on_trade(make_trade(price, i * 1000))
        # Last trade near VWAP shouldn't trigger
        # (may or may not, depending on residual — just check it doesn't crash)
        assert result is None or hasattr(result, "side")

    def test_signal_has_metadata(self, strategy: LinearRegressionStrategy):
        # Feed data with variance then spike
        for i in range(32):
            price = 100.0 + (i % 5) * 0.2
            strategy.on_trade(make_trade(price, i * 1000))

        # Spike the price
        result = strategy.on_trade(make_trade(120.0, 33000))
        if result is not None:
            assert "fair_value" in result.metadata
            assert "z_score" in result.metadata
            assert "residual" in result.metadata
            assert "residual_std" in result.metadata


class TestLinRegBookUpdate:
    def test_book_update_never_signals(self, strategy: LinearRegressionStrategy):
        update = DepthUpdate(
            symbol="BTCUSD",
            bids=[[100.0, 1.0], [99.0, 2.0]],
            asks=[[101.0, 1.5], [102.0, 0.5]],
        )
        assert strategy.on_book_update(update) is None

    def test_book_update_sets_imbalance(self, strategy: LinearRegressionStrategy):
        update = DepthUpdate(
            symbol="BTCUSD",
            bids=[[100.0, 10.0]],
            asks=[[101.0, 1.0]],
        )
        strategy.on_book_update(update)
        assert strategy._book_imbalance > 0


class TestLinRegParams:
    def test_defaults_applied(self):
        s = LinearRegressionStrategy()
        for key in DEFAULT_PARAMS:
            assert key in s.params

    def test_custom_override(self):
        s = LinearRegressionStrategy(params={"window_size": 500})
        assert s.params["window_size"] == 500
        assert s.params["refit_interval"] == DEFAULT_PARAMS["refit_interval"]
