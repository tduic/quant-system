"""Tests for Monte Carlo simulation."""

from __future__ import annotations

from backtest_svc.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    _compute_returns,
    _max_drawdown_from_returns,
    _resample_returns,
    _sharpe_from_returns,
    _total_return_from_returns,
    run_monte_carlo,
)


class TestComputeReturns:
    def test_basic_returns(self):
        equity = [100.0, 110.0, 105.0]
        returns = _compute_returns(equity)
        assert len(returns) == 2
        assert abs(returns[0] - 0.1) < 1e-10
        assert abs(returns[1] - (-5.0 / 110.0)) < 1e-10

    def test_single_value(self):
        assert _compute_returns([100.0]) == []

    def test_empty(self):
        assert _compute_returns([]) == []

    def test_flat_equity(self):
        equity = [100.0, 100.0, 100.0]
        returns = _compute_returns(equity)
        assert all(r == 0.0 for r in returns)


class TestSharpeFromReturns:
    def test_positive_returns(self):
        returns = [0.01, 0.02, 0.01, 0.03, -0.005, 0.015] * 15
        sharpe = _sharpe_from_returns(returns)
        # Positive mean, moderate variance → positive Sharpe
        assert sharpe > 0

    def test_varying_positive(self):
        returns = [0.01, 0.02, 0.01, 0.02, 0.01, 0.015, 0.01, 0.02]
        sharpe = _sharpe_from_returns(returns)
        assert sharpe > 0

    def test_empty(self):
        assert _sharpe_from_returns([]) == 0.0

    def test_single_return(self):
        assert _sharpe_from_returns([0.05]) == 0.0


class TestMaxDrawdownFromReturns:
    def test_no_drawdown(self):
        returns = [0.01, 0.01, 0.01]
        dd = _max_drawdown_from_returns(returns)
        assert dd == 0.0

    def test_full_loss(self):
        returns = [-0.5, -0.5]
        dd = _max_drawdown_from_returns(returns)
        # After -50% then -50%: equity goes 1.0 → 0.5 → 0.25, dd = 75%
        assert abs(dd - 0.75) < 1e-10

    def test_recovery(self):
        returns = [0.1, -0.2, 0.15]
        dd = _max_drawdown_from_returns(returns)
        assert dd > 0

    def test_empty(self):
        assert _max_drawdown_from_returns([]) == 0.0


class TestTotalReturn:
    def test_positive(self):
        returns = [0.1, 0.1, 0.1]
        total = _total_return_from_returns(returns)
        # (1.1)^3 - 1 = 0.331
        assert abs(total - 0.331) < 0.001

    def test_zero(self):
        returns = [0.0, 0.0, 0.0]
        assert _total_return_from_returns(returns) == 0.0

    def test_empty(self):
        assert _total_return_from_returns([]) == 0.0


class TestResampleReturns:
    def test_same_length(self):
        import random

        rng = random.Random(42)
        returns = [0.01, -0.02, 0.03, -0.01, 0.02]
        resampled = _resample_returns(returns, rng)
        assert len(resampled) == len(returns)

    def test_values_from_original(self):
        import random

        rng = random.Random(42)
        returns = [0.01, -0.02, 0.03]
        resampled = _resample_returns(returns, rng)
        for r in resampled:
            assert r in returns

    def test_block_bootstrap(self):
        import random

        rng = random.Random(42)
        returns = list(range(20))
        resampled = _resample_returns(returns, rng, block_size=5)
        assert len(resampled) == 20

    def test_empty(self):
        import random

        rng = random.Random(42)
        assert _resample_returns([], rng) == []


class TestRunMonteCarlo:
    def test_basic_simulation(self):
        equity = [100.0 + i * 0.5 for i in range(100)]
        config = MonteCarloConfig(n_simulations=200, seed=42)

        result = run_monte_carlo(equity, config)

        assert isinstance(result, MonteCarloResult)
        assert result.n_simulations == 200
        assert result.observed_sharpe != 0.0
        assert len(result.sharpe_distribution.simulated_values) == 200

    def test_confidence_intervals(self):
        equity = [100.0 + i * 0.5 + (i % 3) * 0.2 for i in range(200)]
        config = MonteCarloConfig(
            n_simulations=500,
            confidence_levels=[0.05, 0.50, 0.95],
            seed=42,
        )

        result = run_monte_carlo(equity, config)

        cis = result.sharpe_distribution.confidence_intervals
        assert len(cis) == 3
        # 5th percentile < 50th percentile < 95th percentile
        assert cis[0].value <= cis[1].value <= cis[2].value

    def test_prob_positive_sharpe(self):
        # Consistently rising equity → high prob of positive sharpe
        equity = [100.0 + i for i in range(200)]
        config = MonteCarloConfig(n_simulations=500, seed=42)

        result = run_monte_carlo(equity, config)
        assert result.prob_positive_sharpe > 0.5

    def test_block_bootstrap(self):
        equity = [100.0 + i * 0.3 for i in range(100)]
        config = MonteCarloConfig(n_simulations=100, block_size=5, seed=42)

        result = run_monte_carlo(equity, config)
        assert result.n_simulations == 100
        assert len(result.sharpe_distribution.simulated_values) == 100

    def test_reproducible(self):
        equity = [100.0 + i * 0.5 for i in range(100)]
        config = MonteCarloConfig(n_simulations=100, seed=42)

        r1 = run_monte_carlo(equity, config)
        r2 = run_monte_carlo(equity, config)

        assert r1.sharpe_distribution.mean == r2.sharpe_distribution.mean

    def test_empty_equity(self):
        result = run_monte_carlo([])
        assert result.n_simulations == 0

    def test_single_point(self):
        result = run_monte_carlo([100.0])
        assert result.n_simulations == 0

    def test_default_config(self):
        equity = [100.0 + i for i in range(50)]
        result = run_monte_carlo(equity)
        assert result.n_simulations == 1000
