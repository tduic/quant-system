"""Tests for slippage/fee sensitivity sweeps."""

from __future__ import annotations

from typing import Any

from backtest_svc.sensitivity_sweep import (
    SweepConfig,
    SweepResult,
    run_sensitivity_sweep,
)


class MockCostEvaluator:
    """Evaluator where higher fees → lower returns."""

    def __init__(self, base_return: float = 0.10):
        self.call_count = 0
        self._base_return = base_return

    def evaluate(self, trades: list[dict], params: dict[str, Any]) -> dict[str, float]:
        self.call_count += 1
        fee = params.get("fee_rate", 0.006)
        slippage = params.get("slippage_bps", 0.0)

        # Higher fees and slippage reduce returns
        cost_drag = fee * 100 + slippage * 0.01
        net_return = self._base_return - cost_drag
        sharpe = net_return * 10 if net_return > 0 else net_return * 5

        return {
            "sharpe": sharpe,
            "total_return": net_return,
            "max_drawdown": 0.05 + cost_drag * 0.1,
            "total_costs": cost_drag,
            "num_trades": 50,
        }


class TestSweepConfig:
    def test_defaults(self):
        config = SweepConfig()
        assert len(config.fee_rates) > 0
        assert len(config.slippage_bps) > 0
        assert "fee_rate" in config.sweep_dimensions


class TestRunSensitivitySweep:
    def test_basic_sweep(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(
            fee_rates=[0.001, 0.005, 0.01],
            slippage_bps=[0.0, 5.0, 10.0],
            sweep_dimensions=["fee_rate", "slippage_bps"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)

        assert isinstance(result, SweepResult)
        assert len(result.points) == 9  # 3 x 3
        assert evaluator.call_count == 9

    def test_best_case_lowest_costs(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(
            fee_rates=[0.001, 0.01],
            slippage_bps=[0.0, 20.0],
            sweep_dimensions=["fee_rate", "slippage_bps"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)

        # Best case should be lowest fee + lowest slippage
        assert result.best_case.fee_rate == 0.001
        assert result.best_case.slippage_bps == 0.0

    def test_worst_case_highest_costs(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(
            fee_rates=[0.001, 0.01],
            slippage_bps=[0.0, 20.0],
            sweep_dimensions=["fee_rate", "slippage_bps"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        assert result.worst_case.fee_rate == 0.01
        assert result.worst_case.slippage_bps == 20.0

    def test_breakeven_fee(self):
        trades = [{"price": 100.0} for _ in range(100)]
        # base_return=5.0 so even at fee_rate=0.01 (cost_drag=1.0) it's profitable
        evaluator = MockCostEvaluator(base_return=5.0)
        config = SweepConfig(
            fee_rates=[0.001, 0.005, 0.01, 0.10],
            slippage_bps=[0.0],
            sweep_dimensions=["fee_rate"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        # Low fees are profitable, 0.10 fee → cost_drag=10.0 > 5.0 → unprofitable
        assert result.breakeven.max_fee_rate >= 0.001
        assert result.breakeven.max_fee_rate < 0.10

    def test_single_dimension(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(
            fee_rates=[0.001, 0.003, 0.006],
            sweep_dimensions=["fee_rate"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        assert len(result.points) == 3

    def test_sensitivity_to_fees(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(
            fee_rates=[0.001, 0.005, 0.01],
            slippage_bps=[0.0],
            sweep_dimensions=["fee_rate"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        # Sharpe should decrease with higher fees
        assert result.sharpe_sensitivity_to_fees < 0

    def test_base_params_merged(self):
        trades = [{"price": 100.0} for _ in range(100)]

        captured_params = []

        class CapturingEvaluator:
            def evaluate(self, trades, params):
                captured_params.append(params.copy())
                return {"sharpe": 1.0, "total_return": 0.05, "max_drawdown": 0.01, "total_costs": 0.001}

        config = SweepConfig(
            fee_rates=[0.001],
            sweep_dimensions=["fee_rate"],
        )

        run_sensitivity_sweep(
            trades,
            CapturingEvaluator(),
            base_params={"threshold_std": 2.0},
            config=config,
        )

        assert captured_params[0]["threshold_std"] == 2.0
        assert captured_params[0]["fee_rate"] == 0.001

    def test_empty_dimensions(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator()
        config = SweepConfig(sweep_dimensions=[])

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        assert len(result.points) == 0

    def test_net_profitable_flag(self):
        trades = [{"price": 100.0} for _ in range(100)]
        evaluator = MockCostEvaluator(base_return=0.10)
        config = SweepConfig(
            fee_rates=[0.0001, 0.05],  # very low and very high
            slippage_bps=[0.0],
            sweep_dimensions=["fee_rate"],
        )

        result = run_sensitivity_sweep(trades, evaluator, config=config)
        profitables = [p for p in result.points if p.net_profitable]
        unprofitables = [p for p in result.points if not p.net_profitable]
        # Low fee should be profitable, high fee unprofitable
        assert len(profitables) >= 1
        assert len(unprofitables) >= 1
