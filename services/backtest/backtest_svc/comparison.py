"""Backtest comparison — side-by-side metrics for multiple runs.

Loads results from the BacktestResultStore and presents them in a
structured comparison format. Supports ranking by any metric and
computing deltas between runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest_svc.results import BacktestResultStore

logger = logging.getLogger(__name__)


@dataclass
class RunMetrics:
    """Normalized metrics for a single backtest run."""

    backtest_id: str = ""
    symbol: str = ""
    start_time: str = ""
    end_time: str = ""
    trades_replayed: int = 0
    duration_seconds: float = 0.0
    data_span_seconds: float = 0.0
    messages_per_second: float = 0.0
    # Extended metrics (from post-trade analysis when available)
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    num_fills: int = 0


@dataclass
class MetricDelta:
    """Difference between two runs for a specific metric."""

    metric_name: str = ""
    run_a_value: float = 0.0
    run_b_value: float = 0.0
    absolute_delta: float = 0.0
    pct_change: float = 0.0


@dataclass
class PairwiseComparison:
    """Comparison between two specific runs."""

    run_a_id: str = ""
    run_b_id: str = ""
    deltas: list[MetricDelta] = field(default_factory=list)
    better_run: str = ""  # which run has higher Sharpe


@dataclass
class ComparisonResult:
    """Full comparison output."""

    runs: list[RunMetrics] = field(default_factory=list)
    ranked_by_sharpe: list[str] = field(default_factory=list)
    ranked_by_return: list[str] = field(default_factory=list)
    pairwise: list[PairwiseComparison] = field(default_factory=list)


def load_run_metrics(
    store: BacktestResultStore,
    backtest_ids: list[str] | None = None,
) -> list[RunMetrics]:
    """Load metrics for the requested runs (or all runs if none specified)."""
    if backtest_ids:
        raw = [store.get(bid) for bid in backtest_ids]
        raw = [r for r in raw if r is not None]
    else:
        raw = store.list_all()

    metrics = []
    for data in raw:
        m = RunMetrics(
            backtest_id=data.get("backtest_id", ""),
            symbol=data.get("symbol", ""),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            trades_replayed=data.get("trades_replayed", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            data_span_seconds=data.get("data_span_seconds", 0.0),
            messages_per_second=data.get("messages_per_second", 0.0),
            sharpe=data.get("sharpe", 0.0),
            total_return=data.get("total_return", 0.0),
            max_drawdown=data.get("max_drawdown", 0.0),
            win_rate=data.get("win_rate", 0.0),
            profit_factor=data.get("profit_factor", 0.0),
            num_fills=data.get("num_fills", 0),
        )
        metrics.append(m)

    return metrics


def compare_pair(run_a: RunMetrics, run_b: RunMetrics) -> PairwiseComparison:
    """Compare two runs and compute deltas for all numeric metrics."""
    metric_pairs = [
        ("sharpe", run_a.sharpe, run_b.sharpe),
        ("total_return", run_a.total_return, run_b.total_return),
        ("max_drawdown", run_a.max_drawdown, run_b.max_drawdown),
        ("win_rate", run_a.win_rate, run_b.win_rate),
        ("profit_factor", run_a.profit_factor, run_b.profit_factor),
        ("trades_replayed", float(run_a.trades_replayed), float(run_b.trades_replayed)),
        ("messages_per_second", run_a.messages_per_second, run_b.messages_per_second),
    ]

    deltas = []
    for name, val_a, val_b in metric_pairs:
        abs_delta = val_b - val_a
        pct = (abs_delta / abs(val_a) * 100.0) if val_a != 0 else 0.0
        deltas.append(
            MetricDelta(
                metric_name=name,
                run_a_value=val_a,
                run_b_value=val_b,
                absolute_delta=abs_delta,
                pct_change=pct,
            )
        )

    better = run_a.backtest_id if run_a.sharpe >= run_b.sharpe else run_b.backtest_id

    return PairwiseComparison(
        run_a_id=run_a.backtest_id,
        run_b_id=run_b.backtest_id,
        deltas=deltas,
        better_run=better,
    )


def compare_runs(
    store: BacktestResultStore,
    backtest_ids: list[str] | None = None,
) -> ComparisonResult:
    """Compare multiple backtest runs side by side.

    Args:
        store: Result store to load from.
        backtest_ids: Specific runs to compare (all if None).

    Returns:
        ComparisonResult with rankings and pairwise deltas.
    """
    runs = load_run_metrics(store, backtest_ids)

    if not runs:
        return ComparisonResult()

    # Rankings
    ranked_sharpe = sorted(runs, key=lambda r: r.sharpe, reverse=True)
    ranked_return = sorted(runs, key=lambda r: r.total_return, reverse=True)

    # Pairwise comparisons (all pairs)
    pairwise: list[PairwiseComparison] = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            pairwise.append(compare_pair(runs[i], runs[j]))

    return ComparisonResult(
        runs=runs,
        ranked_by_sharpe=[r.backtest_id for r in ranked_sharpe],
        ranked_by_return=[r.backtest_id for r in ranked_return],
        pairwise=pairwise,
    )
