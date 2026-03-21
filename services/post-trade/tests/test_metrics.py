"""Tests for post_trade_svc.metrics — risk-adjusted return metrics."""

from __future__ import annotations

import math

import pytest

from post_trade_svc.metrics import (
    compute_sharpe,
    compute_sortino,
    compute_max_drawdown,
    compute_calmar,
    ANNUAL_FACTOR,
)


class TestSharpe:
    def test_positive_returns(self):
        returns = [0.01, 0.02, 0.01, 0.03, 0.01]
        sharpe = compute_sharpe(returns)
        assert sharpe > 0

    def test_negative_returns(self):
        returns = [-0.01, -0.02, -0.01, -0.03, -0.01]
        sharpe = compute_sharpe(returns)
        assert sharpe < 0

    def test_zero_std_returns_zero(self):
        returns = [0.01, 0.01, 0.01, 0.01]
        assert compute_sharpe(returns) == 0.0

    def test_empty_returns_zero(self):
        assert compute_sharpe([]) == 0.0

    def test_single_return_zero(self):
        assert compute_sharpe([0.01]) == 0.0

    def test_risk_free_rate_subtracted(self):
        returns = [0.01, 0.01, 0.01, 0.01, 0.01]
        # With risk_free = 0.01, excess return = 0, sharpe = 0
        assert compute_sharpe(returns, risk_free_daily=0.01) == 0.0


class TestSortino:
    def test_positive_returns_high_sortino(self):
        returns = [0.01, 0.02, 0.03, 0.01, 0.02]
        sortino = compute_sortino(returns)
        assert sortino > 0

    def test_all_negative_returns(self):
        returns = [-0.01, -0.02, -0.01]
        sortino = compute_sortino(returns)
        assert sortino < 0

    def test_no_downside_returns_inf(self):
        returns = [0.01, 0.02, 0.03]
        sortino = compute_sortino(returns)
        assert sortino == float("inf")

    def test_empty_returns_zero(self):
        assert compute_sortino([]) == 0.0

    def test_sortino_gte_sharpe_for_positive_skew(self):
        # Sortino should be >= Sharpe when there's enough downside data
        returns = [0.05, 0.02, 0.01, -0.01, -0.005, 0.03, 0.04, -0.008, 0.02, 0.01]
        sharpe = compute_sharpe(returns)
        sortino = compute_sortino(returns)
        assert sortino >= sharpe


class TestMaxDrawdown:
    def test_no_drawdown(self):
        equity = [100, 101, 102, 103]
        dd, dur = compute_max_drawdown(equity)
        assert dd == pytest.approx(0.0)
        assert dur == 0

    def test_simple_drawdown(self):
        equity = [100, 90, 95, 100]
        dd, dur = compute_max_drawdown(equity)
        assert dd == pytest.approx(0.10)  # 10% drawdown
        assert dur == 2  # 2 periods underwater

    def test_multiple_drawdowns_returns_max(self):
        equity = [100, 95, 100, 80, 90, 100]
        dd, dur = compute_max_drawdown(equity)
        assert dd == pytest.approx(0.20)  # 20% drawdown

    def test_empty_equity(self):
        dd, dur = compute_max_drawdown([])
        assert dd == 0.0
        assert dur == 0

    def test_single_value(self):
        dd, dur = compute_max_drawdown([100])
        assert dd == 0.0
        assert dur == 0


class TestCalmar:
    def test_positive_calmar(self):
        calmar = compute_calmar(annualized_return=0.20, max_drawdown=0.10)
        assert calmar == pytest.approx(2.0)

    def test_zero_drawdown_returns_zero(self):
        assert compute_calmar(0.20, 0.0) == 0.0

    def test_negative_return(self):
        calmar = compute_calmar(annualized_return=-0.10, max_drawdown=0.20)
        assert calmar == pytest.approx(-0.5)
