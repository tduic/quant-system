"""Tests for parameter sensitivity analysis."""

from __future__ import annotations

from typing import Any

from backtest_svc.param_sensitivity import (
    ParamRange,
    SearchMethod,
    SensitivityPoint,
    SensitivityResult,
    build_grid,
    build_random_samples,
    compute_param_impacts,
    run_sensitivity,
)


class MockEvaluator:
    def __init__(self, sharpe_fn=None):
        self.call_count = 0
        self._sharpe_fn = sharpe_fn

    def evaluate(self, trades: list[dict], params: dict[str, Any]) -> dict[str, float]:
        self.call_count += 1
        sharpe = self._sharpe_fn(params) if self._sharpe_fn else params.get("threshold_std", 1.0) * 0.5
        return {
            "sharpe": sharpe,
            "total_return": sharpe * 0.05,
            "max_drawdown": 0.1,
            "num_trades": 50,
        }


class TestBuildGrid:
    def test_single_param(self):
        ranges = [ParamRange(name="x", values=[1, 2, 3])]
        grid = build_grid(ranges)
        assert len(grid) == 3
        assert grid[0] == {"x": 1}

    def test_two_params(self):
        ranges = [
            ParamRange(name="x", values=[1, 2]),
            ParamRange(name="y", values=[10, 20, 30]),
        ]
        grid = build_grid(ranges)
        assert len(grid) == 6  # 2 * 3

    def test_empty_ranges(self):
        grid = build_grid([])
        assert grid == [{}]

    def test_cartesian_product(self):
        ranges = [
            ParamRange(name="a", values=[1, 2]),
            ParamRange(name="b", values=["x", "y"]),
        ]
        grid = build_grid(ranges)
        assert {"a": 1, "b": "x"} in grid
        assert {"a": 2, "b": "y"} in grid


class TestBuildRandomSamples:
    def test_correct_count(self):
        ranges = [ParamRange(name="x", low=0.0, high=10.0)]
        samples = build_random_samples(ranges, n_samples=20, seed=42)
        assert len(samples) == 20

    def test_reproducible_with_seed(self):
        ranges = [ParamRange(name="x", low=0.0, high=10.0)]
        s1 = build_random_samples(ranges, n_samples=10, seed=42)
        s2 = build_random_samples(ranges, n_samples=10, seed=42)
        assert s1 == s2

    def test_values_in_range(self):
        ranges = [ParamRange(name="x", low=1.0, high=5.0)]
        samples = build_random_samples(ranges, n_samples=100, seed=42)
        for s in samples:
            assert 1.0 <= s["x"] <= 5.0

    def test_log_scale(self):
        ranges = [ParamRange(name="x", low=0.001, high=1.0, log_scale=True)]
        samples = build_random_samples(ranges, n_samples=100, seed=42)
        for s in samples:
            assert 0.001 <= s["x"] <= 1.0

    def test_int_dtype(self):
        ranges = [ParamRange(name="x", low=1.0, high=100.0, dtype="int")]
        samples = build_random_samples(ranges, n_samples=20, seed=42)
        for s in samples:
            assert isinstance(s["x"], int)

    def test_explicit_values_random(self):
        ranges = [ParamRange(name="x", values=[10, 20, 30])]
        samples = build_random_samples(ranges, n_samples=50, seed=42)
        for s in samples:
            assert s["x"] in [10, 20, 30]


class TestComputeParamImpacts:
    def test_single_param_impact(self):
        points = [
            SensitivityPoint(params={"x": 1.0}, sharpe=0.5),
            SensitivityPoint(params={"x": 2.0}, sharpe=1.0),
            SensitivityPoint(params={"x": 3.0}, sharpe=1.5),
        ]
        impacts = compute_param_impacts(points, ["x"])
        assert len(impacts) == 1
        assert impacts[0].param_name == "x"
        assert impacts[0].sharpe_range == 1.0
        assert impacts[0].best_value == 3.0
        assert impacts[0].worst_value == 1.0

    def test_positive_correlation(self):
        points = [
            SensitivityPoint(params={"x": 1.0}, sharpe=1.0),
            SensitivityPoint(params={"x": 2.0}, sharpe=2.0),
            SensitivityPoint(params={"x": 3.0}, sharpe=3.0),
        ]
        impacts = compute_param_impacts(points, ["x"])
        assert impacts[0].correlation_with_sharpe > 0.9

    def test_sorted_by_impact(self):
        points = [
            SensitivityPoint(params={"x": 1.0, "y": 1.0}, sharpe=1.0),
            SensitivityPoint(params={"x": 2.0, "y": 1.0}, sharpe=1.1),
            SensitivityPoint(params={"x": 1.0, "y": 2.0}, sharpe=3.0),
            SensitivityPoint(params={"x": 2.0, "y": 2.0}, sharpe=3.1),
        ]
        impacts = compute_param_impacts(points, ["x", "y"])
        # y has bigger sharpe range than x
        assert impacts[0].param_name == "y"


class TestRunSensitivity:
    def test_grid_search(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockEvaluator()
        ranges = [ParamRange(name="threshold_std", values=[1.0, 2.0, 3.0])]

        result = run_sensitivity(trades, evaluator, ranges, method=SearchMethod.GRID)

        assert isinstance(result, SensitivityResult)
        assert result.num_evaluations == 3
        assert evaluator.call_count == 3
        assert result.best_sharpe > 0

    def test_random_search(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockEvaluator()
        ranges = [ParamRange(name="threshold_std", low=0.5, high=5.0)]

        result = run_sensitivity(
            trades,
            evaluator,
            ranges,
            method=SearchMethod.RANDOM,
            n_random_samples=25,
            random_seed=42,
        )

        assert result.num_evaluations == 25
        assert result.best_params is not None

    def test_best_params_correct(self):
        # Higher threshold_std → higher sharpe in our mock
        def linear_sharpe(params):
            return params.get("threshold_std", 0.0) * 2.0

        evaluator = MockEvaluator(sharpe_fn=linear_sharpe)
        trades = [{"price": 100.0} for _ in range(100)]
        ranges = [ParamRange(name="threshold_std", values=[1.0, 2.0, 3.0])]

        result = run_sensitivity(trades, evaluator, ranges)

        assert result.best_params["threshold_std"] == 3.0
        assert result.best_sharpe == 6.0

    def test_param_impacts_included(self):
        evaluator = MockEvaluator()
        trades = [{"price": 100.0} for _ in range(100)]
        ranges = [
            ParamRange(name="threshold_std", values=[1.0, 2.0, 3.0]),
            ParamRange(name="window_size", values=[50, 100]),
        ]

        result = run_sensitivity(trades, evaluator, ranges)
        assert len(result.param_impacts) == 2
