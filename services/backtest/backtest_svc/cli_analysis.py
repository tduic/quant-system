"""CLI commands for backtest analysis — no Kafka/DB dependencies.

These commands operate on trade data files (JSON lines) and the local
result store. They can be run independently from the replay engine.

Usage:
    python -m backtest_svc.cli_analysis sensitivity --trades trades.jsonl --strategy mean_reversion
    python -m backtest_svc.cli_analysis walk-forward --trades trades.jsonl --strategy mean_reversion --splits 5
    python -m backtest_svc.cli_analysis monte-carlo --equity equity.json --simulations 1000
    python -m backtest_svc.cli_analysis validate --trades trades.jsonl --equity equity.json --strategy mean_reversion
    python -m backtest_svc.cli_analysis compare --ids bt-abc123 bt-def456
"""

from __future__ import annotations

import argparse
import json
import logging

logger = logging.getLogger(__name__)


def _load_trades(path: str) -> list[dict]:
    """Load trades from JSON lines file."""
    trades = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                trades.append(json.loads(line))
    return trades


def _load_equity(path: str) -> list[float]:
    """Load equity curve from JSON file (list of floats)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return [float(v) for v in data]
    # Support {"equity_curve": [...]} format
    if isinstance(data, dict) and "equity_curve" in data:
        return [float(v) for v in data["equity_curve"]]
    return []


def _generate_sample_trades(symbol: str = "BTCUSD", n: int = 500) -> list[dict]:
    """Generate synthetic trade data for testing."""
    import random

    rng = random.Random(42)
    price = 50000.0
    trades = []
    for i in range(n):
        # Random walk with mean reversion
        price += rng.gauss(0, 50) - (price - 50000) * 0.001
        price = max(price, 100)
        trades.append(
            {
                "symbol": symbol,
                "price": round(price, 2),
                "quantity": round(rng.uniform(0.001, 0.1), 4),
                "timestamp_exchange": 1000000 + i * 1000,
                "is_buyer_maker": rng.random() > 0.5,
            }
        )
    return trades


def cmd_sensitivity(args: argparse.Namespace) -> None:
    """Run parameter sensitivity analysis."""
    from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator
    from backtest_svc.param_sensitivity import ParamRange, SearchMethod, run_sensitivity

    if args.trades:
        trades = _load_trades(args.trades)
    else:
        print("No --trades file provided, using synthetic data.")
        trades = _generate_sample_trades(args.symbol, n=args.num_trades)

    config = EvaluatorConfig(
        strategy_type=args.strategy,
        symbol=args.symbol,
        fee_rate=args.fee_rate,
        slippage_bps=args.slippage_bps,
    )
    evaluator = LocalStrategyEvaluator(config)

    # Build param ranges based on strategy type
    if args.strategy == "mean_reversion":
        param_ranges = [
            ParamRange(name="threshold_std", values=[1.0, 1.5, 2.0, 2.5, 3.0]),
            ParamRange(name="window_size", values=[50, 100, 200]),
            ParamRange(name="cooldown_trades", values=[5, 10, 20]),
        ]
    elif args.strategy == "pairs_trading":
        param_ranges = [
            ParamRange(name="entry_threshold", values=[1.5, 2.0, 2.5, 3.0]),
            ParamRange(name="min_correlation", values=[0.3, 0.5, 0.7]),
            ParamRange(name="window", values=[50, 100, 200]),
        ]
    else:
        print(f"Unknown strategy: {args.strategy}")
        return

    method = SearchMethod.RANDOM if args.random else SearchMethod.GRID
    result = run_sensitivity(
        trades,
        evaluator,
        param_ranges,
        method=method,
        n_random_samples=args.random_samples,
        random_seed=args.seed,
    )

    print(f"\n{'=' * 60}")
    print(f"  Parameter Sensitivity Analysis ({result.search_method})")
    print(f"{'=' * 60}")
    print(f"  Evaluations: {result.num_evaluations}")
    print(f"  Best Sharpe:  {result.best_sharpe:.4f}")
    print(f"  Best params:  {result.best_params}")
    print()
    print("  Parameter Impacts:")
    for impact in result.param_impacts:
        print(
            f"    {impact.param_name:<20} "
            f"range={impact.sharpe_range:.4f}  "
            f"corr={impact.correlation_with_sharpe:.3f}  "
            f"best={impact.best_value}  worst={impact.worst_value}"
        )
    print(f"{'=' * 60}\n")

    if args.output:
        _write_json(
            args.output,
            {
                "best_params": result.best_params,
                "best_sharpe": result.best_sharpe,
                "num_evaluations": result.num_evaluations,
                "param_impacts": [
                    {
                        "name": i.param_name,
                        "sharpe_range": i.sharpe_range,
                        "correlation": i.correlation_with_sharpe,
                        "best_value": i.best_value,
                        "worst_value": i.worst_value,
                    }
                    for i in result.param_impacts
                ],
            },
        )


def cmd_walk_forward(args: argparse.Namespace) -> None:
    """Run walk-forward optimization."""
    from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator
    from backtest_svc.param_sensitivity import ParamRange, build_grid
    from backtest_svc.walk_forward import WalkForwardConfig, WindowType, run_walk_forward

    if args.trades:
        trades = _load_trades(args.trades)
    else:
        print("No --trades file provided, using synthetic data.")
        trades = _generate_sample_trades(args.symbol, n=args.num_trades)

    config = EvaluatorConfig(
        strategy_type=args.strategy,
        symbol=args.symbol,
    )
    evaluator = LocalStrategyEvaluator(config)

    if args.strategy == "mean_reversion":
        param_ranges = [
            ParamRange(name="threshold_std", values=[1.5, 2.0, 2.5]),
            ParamRange(name="window_size", values=[50, 100]),
        ]
    else:
        param_ranges = [
            ParamRange(name="entry_threshold", values=[1.5, 2.0, 2.5]),
            ParamRange(name="min_correlation", values=[0.3, 0.5]),
        ]

    param_grid = build_grid(param_ranges)
    window_type = WindowType.EXPANDING if args.expanding else WindowType.ROLLING

    wf_config = WalkForwardConfig(
        n_splits=args.splits,
        train_pct=args.train_pct,
        window_type=window_type,
        min_train_size=args.min_train,
        min_test_size=args.min_test,
    )

    result = run_walk_forward(trades, evaluator, param_grid, wf_config)

    print(f"\n{'=' * 60}")
    print(f"  Walk-Forward Optimization ({window_type})")
    print(f"{'=' * 60}")
    print(f"  Folds:               {len(result.folds)}")
    print(f"  Mean test Sharpe:    {result.mean_test_sharpe:.4f}")
    print(f"  Std test Sharpe:     {result.std_test_sharpe:.4f}")
    print(f"  Mean test return:    {result.mean_test_return:.4%}")
    print(f"  Overfitting ratio:   {result.overfitting_ratio:.2f}x")
    print(f"  Degradation:         {result.degradation_pct:.1f}%")
    print()
    for fold in result.folds:
        print(
            f"  Fold {fold.fold_index}: "
            f"train_sharpe={fold.train_sharpe:.3f}  "
            f"test_sharpe={fold.test_sharpe:.3f}  "
            f"params={fold.best_params}"
        )
    print(f"{'=' * 60}\n")

    if args.output:
        _write_json(
            args.output,
            {
                "mean_test_sharpe": result.mean_test_sharpe,
                "std_test_sharpe": result.std_test_sharpe,
                "overfitting_ratio": result.overfitting_ratio,
                "degradation_pct": result.degradation_pct,
                "folds": [
                    {
                        "fold": f.fold_index,
                        "train_sharpe": f.train_sharpe,
                        "test_sharpe": f.test_sharpe,
                        "best_params": f.best_params,
                    }
                    for f in result.folds
                ],
            },
        )


def cmd_monte_carlo(args: argparse.Namespace) -> None:
    """Run Monte Carlo simulation."""
    from backtest_svc.monte_carlo import MonteCarloConfig, run_monte_carlo

    if args.equity:
        equity = _load_equity(args.equity)
    elif args.trades:
        # Generate equity from trades using evaluator
        from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator

        trades = _load_trades(args.trades)
        evaluator = LocalStrategyEvaluator(EvaluatorConfig(strategy_type=args.strategy, symbol=args.symbol))
        metrics = evaluator.evaluate(trades, {})
        # Create a simple equity curve from the return
        initial = 100_000.0
        final = initial * (1 + metrics["total_return"])
        n = max(len(trades) // 10, 2)
        step = (final - initial) / n
        equity = [initial + i * step for i in range(n + 1)]
    else:
        print("Provide --equity or --trades for Monte Carlo simulation.")
        return

    mc_config = MonteCarloConfig(
        n_simulations=args.simulations,
        block_size=args.block_size,
        seed=args.seed,
    )

    result = run_monte_carlo(equity, mc_config)

    print(f"\n{'=' * 60}")
    print(f"  Monte Carlo Simulation ({result.n_simulations} runs)")
    print(f"{'=' * 60}")
    print(f"  Observed Sharpe:     {result.observed_sharpe:.4f}")
    print(f"  Observed return:     {result.observed_total_return:.4%}")
    print(f"  Observed max DD:     {result.observed_max_drawdown:.4%}")
    print()
    print(f"  Simulated Sharpe:    {result.sharpe_distribution.mean:.4f} +/- {result.sharpe_distribution.std:.4f}")
    print(f"  P(Sharpe > 0):       {result.prob_positive_sharpe:.1%}")
    print(f"  P(Sharpe > 1):       {result.prob_sharpe_above_1:.1%}")
    print()
    print("  Sharpe Confidence Intervals:")
    for ci in result.sharpe_distribution.confidence_intervals:
        print(f"    {ci.level:>6.0%}: {ci.value:.4f}")
    print(f"{'=' * 60}\n")

    if args.output:
        _write_json(
            args.output,
            {
                "observed_sharpe": result.observed_sharpe,
                "observed_return": result.observed_total_return,
                "observed_max_drawdown": result.observed_max_drawdown,
                "prob_positive_sharpe": result.prob_positive_sharpe,
                "prob_sharpe_above_1": result.prob_sharpe_above_1,
                "sharpe_mean": result.sharpe_distribution.mean,
                "sharpe_std": result.sharpe_distribution.std,
                "confidence_intervals": [
                    {"level": ci.level, "value": ci.value} for ci in result.sharpe_distribution.confidence_intervals
                ],
            },
        )


def cmd_cost_sweep(args: argparse.Namespace) -> None:
    """Run slippage/fee sensitivity sweep."""
    from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator
    from backtest_svc.sensitivity_sweep import SweepConfig, run_sensitivity_sweep

    if args.trades:
        trades = _load_trades(args.trades)
    else:
        print("No --trades file provided, using synthetic data.")
        trades = _generate_sample_trades(args.symbol, n=args.num_trades)

    config = EvaluatorConfig(strategy_type=args.strategy, symbol=args.symbol)
    evaluator = LocalStrategyEvaluator(config)

    sweep_config = SweepConfig(
        fee_rates=[0.001, 0.002, 0.004, 0.006, 0.008, 0.01],
        slippage_bps=[0.0, 1.0, 2.5, 5.0, 10.0, 20.0],
        sweep_dimensions=args.dimensions.split(","),
    )

    result = run_sensitivity_sweep(
        trades,
        evaluator,
        base_params={"threshold_std": 2.0},
        config=sweep_config,
    )

    print(f"\n{'=' * 60}")
    print("  Slippage/Fee Sensitivity Sweep")
    print(f"{'=' * 60}")
    print(f"  Scenarios evaluated: {len(result.points)}")
    print(
        f"  Best Sharpe:         {result.best_case.sharpe:.4f} (fee={result.best_case.fee_rate:.1%}, slip={result.best_case.slippage_bps:.1f}bps)"
    )
    print(
        f"  Worst Sharpe:        {result.worst_case.sharpe:.4f} (fee={result.worst_case.fee_rate:.1%}, slip={result.worst_case.slippage_bps:.1f}bps)"
    )
    print()
    print("  Breakeven:")
    print(f"    Max fee rate:      {result.breakeven.max_fee_rate:.2%}")
    print(f"    Max slippage:      {result.breakeven.max_slippage_bps:.1f} bps")
    print()
    print(f"  dSharpe/dFee:        {result.sharpe_sensitivity_to_fees:.1f}")
    print(f"  dSharpe/dSlippage:   {result.sharpe_sensitivity_to_slippage:.4f}")
    print(f"{'=' * 60}\n")

    if args.output:
        _write_json(
            args.output,
            {
                "best_sharpe": result.best_case.sharpe,
                "worst_sharpe": result.worst_case.sharpe,
                "breakeven_fee": result.breakeven.max_fee_rate,
                "breakeven_slippage_bps": result.breakeven.max_slippage_bps,
                "sensitivity_to_fees": result.sharpe_sensitivity_to_fees,
                "sensitivity_to_slippage": result.sharpe_sensitivity_to_slippage,
                "num_scenarios": len(result.points),
            },
        )


def cmd_validate(args: argparse.Namespace) -> None:
    """Run full out-of-sample validation."""
    from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator
    from backtest_svc.monte_carlo import MonteCarloConfig, run_monte_carlo
    from backtest_svc.param_sensitivity import ParamRange, build_grid
    from backtest_svc.sensitivity_sweep import SweepConfig, run_sensitivity_sweep
    from backtest_svc.validation import generate_validation_report
    from backtest_svc.walk_forward import WalkForwardConfig, run_walk_forward

    if args.trades:
        trades = _load_trades(args.trades)
    else:
        print("No --trades file provided, using synthetic data.")
        trades = _generate_sample_trades(args.symbol, n=args.num_trades)

    config = EvaluatorConfig(strategy_type=args.strategy, symbol=args.symbol)
    evaluator = LocalStrategyEvaluator(config)

    print("Running walk-forward optimization...")
    param_grid = build_grid(
        [
            ParamRange(name="threshold_std", values=[1.5, 2.0, 2.5]),
            ParamRange(name="window_size", values=[50, 100]),
        ]
    )
    wf_result = run_walk_forward(
        trades,
        evaluator,
        param_grid,
        WalkForwardConfig(n_splits=args.splits, min_train_size=50, min_test_size=20),
    )

    print("Running Monte Carlo simulation...")
    # Build equity from a default run
    baseline = evaluator.evaluate(trades, {"threshold_std": 2.0})
    initial = 100_000.0
    final = initial * (1 + baseline["total_return"])
    n_eq = max(len(trades) // 10, 2)
    step = (final - initial) / n_eq
    equity = [initial + i * step for i in range(n_eq + 1)]

    mc_result = run_monte_carlo(equity, MonteCarloConfig(n_simulations=args.simulations, seed=args.seed))

    print("Running cost sensitivity sweep...")
    sweep_result = run_sensitivity_sweep(
        trades,
        evaluator,
        base_params={"threshold_std": 2.0},
        config=SweepConfig(sweep_dimensions=["fee_rate", "slippage_bps"]),
    )

    report = generate_validation_report(wf_result, mc_result, sweep_result)

    print(f"\n{'=' * 60}")
    print("  OUT-OF-SAMPLE VALIDATION REPORT")
    print(f"{'=' * 60}")
    print(f"  Grade:               {report.grade.value}")
    print(f"  OOS Sharpe:          {report.mean_oos_sharpe:.4f}")
    print(f"  Overfitting ratio:   {report.overfitting_ratio:.2f}x")
    print(f"  P(Sharpe > 0):       {report.prob_positive_sharpe:.1%}")
    print(f"  Max profitable fee:  {report.max_profitable_fee:.2%}")
    print(f"  Max profitable slip: {report.max_profitable_slippage_bps:.1f} bps")
    print()
    print("  Flags:")
    for flag in report.flags:
        icon = {"info": "  ", "warning": "! ", "critical": "!!"}[flag.severity]
        print(f"    {icon} [{flag.category}] {flag.message}")
    print()
    print(f"  {report.summary}")
    print(f"{'=' * 60}\n")

    if args.output:
        _write_json(
            args.output,
            {
                "grade": report.grade.value,
                "mean_oos_sharpe": report.mean_oos_sharpe,
                "overfitting_ratio": report.overfitting_ratio,
                "prob_positive_sharpe": report.prob_positive_sharpe,
                "max_profitable_fee": report.max_profitable_fee,
                "max_profitable_slippage_bps": report.max_profitable_slippage_bps,
                "flags": [{"category": f.category, "severity": f.severity, "message": f.message} for f in report.flags],
                "summary": report.summary,
            },
        )


def cmd_compare(args: argparse.Namespace) -> None:
    """Compare multiple backtest runs."""
    from backtest_svc.comparison import compare_runs
    from backtest_svc.results import BacktestResultStore

    store = BacktestResultStore()
    result = compare_runs(store, args.ids if args.ids else None)

    if not result.runs:
        print("No runs found to compare.")
        return

    print(f"\n{'=' * 60}")
    print("  Backtest Comparison")
    print(f"{'=' * 60}")
    print(f"\n  {'ID':<20} {'Sharpe':>8} {'Return':>10} {'Max DD':>8} {'Trades':>8}")
    print(f"  {'-' * 56}")
    for run in result.runs:
        print(
            f"  {run.backtest_id:<20} "
            f"{run.sharpe:>8.4f} "
            f"{run.total_return:>9.4%} "
            f"{run.max_drawdown:>7.4%} "
            f"{run.trades_replayed:>8,}"
        )

    print(f"\n  Ranked by Sharpe:  {' > '.join(result.ranked_by_sharpe)}")
    print(f"  Ranked by Return:  {' > '.join(result.ranked_by_return)}")

    if result.pairwise:
        print("\n  Pairwise Comparisons:")
        for pw in result.pairwise:
            sharpe_d = next(d for d in pw.deltas if d.metric_name == "sharpe")
            print(
                f"    {pw.run_a_id} vs {pw.run_b_id}: "
                f"Sharpe delta={sharpe_d.absolute_delta:+.4f} "
                f"({sharpe_d.pct_change:+.1f}%) "
                f"better={pw.better_run}"
            )

    print(f"{'=' * 60}\n")


def _write_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Results written to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest Analysis CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  sensitivity    Parameter sensitivity analysis (grid/random search)
  walk-forward   Walk-forward optimization with rolling train/test splits
  monte-carlo    Monte Carlo bootstrap simulation for confidence intervals
  cost-sweep     Slippage and fee sensitivity sweep
  validate       Full out-of-sample validation (combines all analyses)
  compare        Compare multiple backtest runs side-by-side
        """,
    )

    # Common args
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--trades", help="Path to trades JSONL file")
    common.add_argument("--symbol", default="BTCUSD", help="Trading symbol")
    common.add_argument("--strategy", default="mean_reversion", choices=["mean_reversion", "pairs_trading"])
    common.add_argument("--output", "-o", help="Write results to JSON file")
    common.add_argument("--num-trades", type=int, default=1000, help="Number of synthetic trades if no file")
    common.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    subparsers = parser.add_subparsers(dest="command")

    # sensitivity
    sens_p = subparsers.add_parser("sensitivity", parents=[common], help="Parameter sensitivity analysis")
    sens_p.add_argument("--random", action="store_true", help="Use random search instead of grid")
    sens_p.add_argument("--random-samples", type=int, default=50, help="Number of random samples")
    sens_p.add_argument("--fee-rate", type=float, default=0.006)
    sens_p.add_argument("--slippage-bps", type=float, default=1.0)

    # walk-forward
    wf_p = subparsers.add_parser("walk-forward", parents=[common], help="Walk-forward optimization")
    wf_p.add_argument("--splits", type=int, default=5, help="Number of train/test folds")
    wf_p.add_argument("--train-pct", type=float, default=0.7, help="Training fraction per fold")
    wf_p.add_argument("--expanding", action="store_true", help="Use expanding window (default: rolling)")
    wf_p.add_argument("--min-train", type=int, default=50)
    wf_p.add_argument("--min-test", type=int, default=20)

    # monte-carlo
    mc_p = subparsers.add_parser("monte-carlo", parents=[common], help="Monte Carlo simulation")
    mc_p.add_argument("--equity", help="Path to equity curve JSON file")
    mc_p.add_argument("--simulations", type=int, default=1000)
    mc_p.add_argument("--block-size", type=int, default=1, help="Block bootstrap size (1=standard)")

    # cost-sweep
    cs_p = subparsers.add_parser("cost-sweep", parents=[common], help="Fee/slippage sensitivity sweep")
    cs_p.add_argument("--dimensions", default="fee_rate,slippage_bps", help="Comma-separated dimensions to sweep")

    # validate
    val_p = subparsers.add_parser("validate", parents=[common], help="Full out-of-sample validation")
    val_p.add_argument("--splits", type=int, default=5)
    val_p.add_argument("--simulations", type=int, default=500)

    # compare
    cmp_p = subparsers.add_parser("compare", help="Compare backtest runs")
    cmp_p.add_argument("--ids", nargs="*", help="Specific backtest IDs to compare")

    args = parser.parse_args()

    if args.command == "sensitivity":
        cmd_sensitivity(args)
    elif args.command == "walk-forward":
        cmd_walk_forward(args)
    elif args.command == "monte-carlo":
        cmd_monte_carlo(args)
    elif args.command == "cost-sweep":
        cmd_cost_sweep(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "compare":
        cmd_compare(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
