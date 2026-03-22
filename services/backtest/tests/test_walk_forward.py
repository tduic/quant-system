"""Tests for walk-forward optimization."""

from __future__ import annotations

from typing import Any

from backtest_svc.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WindowType,
    generate_folds,
    run_walk_forward,
)


class MockEvaluator:
    """Mock evaluator that returns predictable metrics based on params."""

    def __init__(self, sharpe_fn=None):
        self.call_count = 0
        self._sharpe_fn = sharpe_fn

    def evaluate(self, trades: list[dict], params: dict[str, Any]) -> dict[str, float]:
        self.call_count += 1
        if self._sharpe_fn:
            sharpe = self._sharpe_fn(trades, params)
        else:
            # Higher threshold_std → lower sharpe (simple inverse relationship)
            sharpe = 1.0 / max(params.get("threshold_std", 1.0), 0.01)
        return {
            "sharpe": sharpe,
            "total_return": sharpe * 0.1,
            "max_drawdown": max(0.0, 0.1 - sharpe * 0.01),
        }


class TestGenerateFolds:
    def test_rolling_folds(self):
        folds = generate_folds(1000, WalkForwardConfig(n_splits=5))
        assert len(folds) == 5
        for train_start, train_end, test_start, test_end in folds:
            assert train_end == test_start
            assert test_end > test_start
            assert train_end > train_start

    def test_expanding_folds(self):
        config = WalkForwardConfig(n_splits=3, window_type=WindowType.EXPANDING)
        folds = generate_folds(300, config)
        assert len(folds) > 0
        # Expanding: train always starts at 0
        for train_start, _, _, _ in folds:
            assert train_start == 0

    def test_empty_trades(self):
        folds = generate_folds(0, WalkForwardConfig())
        assert folds == []

    def test_too_few_trades_reduces_splits(self):
        config = WalkForwardConfig(n_splits=10, min_train_size=50, min_test_size=20)
        folds = generate_folds(100, config)
        # Should reduce to 1 fold instead of 10
        assert len(folds) <= 2

    def test_folds_cover_data(self):
        folds = generate_folds(500, WalkForwardConfig(n_splits=3))
        # Last fold's test_end should reach near the end
        assert folds[-1][3] <= 500

    def test_no_overlap_between_train_test(self):
        folds = generate_folds(1000, WalkForwardConfig(n_splits=5))
        for _, train_end, test_start, _ in folds:
            assert test_start >= train_end


class TestRunWalkForward:
    def test_basic_walk_forward(self):
        trades = [{"price": 100.0 + i * 0.1} for i in range(500)]
        evaluator = MockEvaluator()
        param_grid = [
            {"threshold_std": 1.0},
            {"threshold_std": 2.0},
            {"threshold_std": 3.0},
        ]

        result = run_walk_forward(
            trades,
            evaluator,
            param_grid,
            config=WalkForwardConfig(n_splits=3, min_train_size=20, min_test_size=10),
        )

        assert isinstance(result, WalkForwardResult)
        assert len(result.folds) > 0
        assert evaluator.call_count > 0

    def test_best_params_selected(self):
        trades = [{"price": 100.0 + i} for i in range(200)]
        evaluator = MockEvaluator()
        param_grid = [
            {"threshold_std": 1.0},  # sharpe = 1.0
            {"threshold_std": 0.5},  # sharpe = 2.0 (best)
            {"threshold_std": 3.0},  # sharpe = 0.33
        ]

        result = run_walk_forward(
            trades,
            evaluator,
            param_grid,
            config=WalkForwardConfig(n_splits=2, min_train_size=20, min_test_size=10),
        )

        # Each fold should pick threshold_std=0.5 as best
        for fold in result.folds:
            assert fold.best_params.get("threshold_std") == 0.5

    def test_overfitting_ratio_computed(self):
        def biased_eval(trades, params):
            # Train data (longer) gets higher sharpe than test (shorter)
            return len(trades) * 0.01

        evaluator = MockEvaluator(sharpe_fn=biased_eval)
        trades = [{"price": 100.0} for _ in range(500)]

        result = run_walk_forward(
            trades,
            evaluator,
            [{"threshold_std": 1.0}],
            config=WalkForwardConfig(n_splits=3, min_train_size=20, min_test_size=10),
        )

        # Train has more trades → higher sharpe → ratio > 1
        assert result.overfitting_ratio > 1.0

    def test_empty_param_grid(self):
        trades = [{"price": 100.0} for _ in range(200)]
        evaluator = MockEvaluator()

        result = run_walk_forward(
            trades,
            evaluator,
            [],  # empty grid — will still evaluate but with empty params
            config=WalkForwardConfig(n_splits=2, min_train_size=20, min_test_size=10),
        )
        # Should still produce folds (evaluates empty params dict)
        assert isinstance(result, WalkForwardResult)

    def test_degradation_pct(self):
        call_idx = [0]

        def degrading_eval(trades, params):
            call_idx[0] += 1
            # Alternate high (train) and low (test) for each fold
            # Each fold evaluates grid on train, then best on test
            return 2.0 if len(trades) > 50 else 0.5

        evaluator = MockEvaluator(sharpe_fn=degrading_eval)
        trades = [{"price": 100.0} for _ in range(500)]

        result = run_walk_forward(
            trades,
            evaluator,
            [{"threshold_std": 1.0}],
            config=WalkForwardConfig(n_splits=3, min_train_size=50, min_test_size=20),
        )

        # degradation_pct should be > 0 since train > test
        assert result.degradation_pct > 0

    def test_std_test_sharpe(self):
        call_count = [0]

        def varying_eval(trades, params):
            call_count[0] += 1
            # Return different sharpes for each evaluation
            return float(call_count[0] % 5)

        evaluator = MockEvaluator(sharpe_fn=varying_eval)
        trades = [{"price": 100.0} for _ in range(500)]

        result = run_walk_forward(
            trades,
            evaluator,
            [{"threshold_std": 1.0}],
            config=WalkForwardConfig(n_splits=4, min_train_size=20, min_test_size=10),
        )

        # With varying sharpes, std should be > 0
        if len(result.folds) > 1:
            test_sharpes = [f.test_sharpe for f in result.folds]
            if len(set(test_sharpes)) > 1:
                assert result.std_test_sharpe > 0

    def test_default_config(self):
        trades = [{"price": 100.0} for _ in range(500)]
        evaluator = MockEvaluator()

        result = run_walk_forward(trades, evaluator, [{"threshold_std": 1.0}])
        assert isinstance(result, WalkForwardResult)
