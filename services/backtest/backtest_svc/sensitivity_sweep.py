"""Slippage and fee sensitivity sweeps.

Evaluates how sensitive backtest performance is to transaction cost
assumptions. A strategy that looks great at 0.1% slippage but dies
at 0.3% is fragile and probably not robust enough to trade live.

Sweep dimensions:
    - Fee rate: taker fees (e.g., 0.1% to 1.0%)
    - Slippage bps: additional market impact in basis points
    - Latency ms: order-to-fill delay affecting Brownian bridge slippage
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class SweepConfig:
    """Configuration for a slippage/fee sweep."""

    fee_rates: list[float] = field(default_factory=lambda: [0.001, 0.002, 0.004, 0.006, 0.008, 0.01])
    slippage_bps: list[float] = field(default_factory=lambda: [0.0, 1.0, 2.5, 5.0, 10.0, 20.0])
    latency_ms: list[float] = field(default_factory=lambda: [10.0, 25.0, 50.0, 100.0, 200.0])
    sweep_dimensions: list[str] = field(
        default_factory=lambda: ["fee_rate", "slippage_bps"]
    )  # which dimensions to sweep


@dataclass
class SweepPoint:
    """Result of one cost scenario."""

    fee_rate: float = 0.0
    slippage_bps: float = 0.0
    latency_ms: float = 50.0
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    total_costs: float = 0.0  # total fees + slippage paid
    cost_as_pct_of_pnl: float = 0.0  # costs / gross_pnl
    num_trades: int = 0
    net_profitable: bool = True


@dataclass
class BreakevenAnalysis:
    """Where the strategy stops being profitable."""

    max_fee_rate: float = 0.0  # highest fee that still yields positive return
    max_slippage_bps: float = 0.0  # highest slippage that still profits
    max_latency_ms: float = 0.0


@dataclass
class SweepResult:
    """Full sweep output."""

    points: list[SweepPoint] = field(default_factory=list)
    breakeven: BreakevenAnalysis = field(default_factory=BreakevenAnalysis)
    best_case: SweepPoint = field(default_factory=SweepPoint)
    worst_case: SweepPoint = field(default_factory=SweepPoint)
    sharpe_sensitivity_to_fees: float = 0.0  # dSharpe/dFee
    sharpe_sensitivity_to_slippage: float = 0.0  # dSharpe/dSlippage


class CostAwareEvaluator(Protocol):
    """Protocol for evaluators that accept cost parameters."""

    def evaluate(
        self,
        trades: list[dict],
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Evaluate with cost params included in the params dict.

        Expected keys in params: 'fee_rate', 'slippage_bps', 'latency_ms'.
        Returns dict with: 'sharpe', 'total_return', 'max_drawdown',
        'total_costs', 'num_trades'.
        """
        ...


def _compute_sensitivity(
    points: list[SweepPoint],
    dimension: str,
) -> float:
    """Linear sensitivity of Sharpe to a cost dimension.

    Returns approximate dSharpe / d(dimension) via simple regression.
    """
    if len(points) < 2:
        return 0.0

    xs = [getattr(p, dimension, 0.0) for p in points]
    ys = [p.sharpe for p in points]

    # Deduplicate by averaging y for same x
    grouped: dict[float, list[float]] = {}
    for x, y in zip(xs, ys, strict=True):
        grouped.setdefault(x, []).append(y)

    x_vals = sorted(grouped.keys())
    if len(x_vals) < 2:
        return 0.0

    y_means = [sum(grouped[x]) / len(grouped[x]) for x in x_vals]

    # Simple slope: (y_last - y_first) / (x_last - x_first)
    dx = x_vals[-1] - x_vals[0]
    if dx == 0:
        return 0.0
    return (y_means[-1] - y_means[0]) / dx


def run_sensitivity_sweep(
    trades: list[dict],
    evaluator: CostAwareEvaluator,
    base_params: dict[str, Any] | None = None,
    config: SweepConfig | None = None,
) -> SweepResult:
    """Run slippage and fee sensitivity sweep.

    Args:
        trades: Trade data for evaluation.
        evaluator: Cost-aware strategy evaluator.
        base_params: Base strategy params (cost params will be merged in).
        config: Sweep configuration.

    Returns:
        SweepResult with all scenarios and breakeven analysis.
    """
    if config is None:
        config = SweepConfig()
    if base_params is None:
        base_params = {}

    # Build sweep combinations
    dims: dict[str, list[float]] = {}
    for dim_name in config.sweep_dimensions:
        if dim_name == "fee_rate":
            dims[dim_name] = config.fee_rates
        elif dim_name == "slippage_bps":
            dims[dim_name] = config.slippage_bps
        elif dim_name == "latency_ms":
            dims[dim_name] = config.latency_ms

    if not dims:
        return SweepResult()

    dim_names = list(dims.keys())
    dim_values = [dims[n] for n in dim_names]

    points: list[SweepPoint] = []

    for combo in itertools.product(*dim_values):
        cost_params = dict(zip(dim_names, combo, strict=True))
        merged = {**base_params, **cost_params}

        metrics = evaluator.evaluate(trades, merged)

        total_return = metrics.get("total_return", 0.0)
        total_costs = metrics.get("total_costs", 0.0)

        point = SweepPoint(
            fee_rate=cost_params.get("fee_rate", base_params.get("fee_rate", 0.006)),
            slippage_bps=cost_params.get("slippage_bps", base_params.get("slippage_bps", 0.0)),
            latency_ms=cost_params.get("latency_ms", base_params.get("latency_ms", 50.0)),
            sharpe=metrics.get("sharpe", 0.0),
            total_return=total_return,
            max_drawdown=metrics.get("max_drawdown", 0.0),
            total_costs=total_costs,
            cost_as_pct_of_pnl=(abs(total_costs / total_return * 100.0) if total_return != 0 else 0.0),
            num_trades=int(metrics.get("num_trades", 0)),
            net_profitable=total_return > 0,
        )
        points.append(point)

    if not points:
        return SweepResult()

    # Best/worst case
    best = max(points, key=lambda p: p.sharpe)
    worst = min(points, key=lambda p: p.sharpe)

    # Breakeven analysis
    breakeven = BreakevenAnalysis()

    # Max profitable fee rate
    fee_points = sorted(
        [p for p in points if p.net_profitable],
        key=lambda p: p.fee_rate,
        reverse=True,
    )
    if fee_points:
        breakeven.max_fee_rate = fee_points[0].fee_rate

    # Max profitable slippage
    slip_points = sorted(
        [p for p in points if p.net_profitable],
        key=lambda p: p.slippage_bps,
        reverse=True,
    )
    if slip_points:
        breakeven.max_slippage_bps = slip_points[0].slippage_bps

    # Max profitable latency
    lat_points = sorted(
        [p for p in points if p.net_profitable],
        key=lambda p: p.latency_ms,
        reverse=True,
    )
    if lat_points:
        breakeven.max_latency_ms = lat_points[0].latency_ms

    # Sensitivities
    fee_sens = _compute_sensitivity(points, "fee_rate")
    slip_sens = _compute_sensitivity(points, "slippage_bps")

    return SweepResult(
        points=points,
        breakeven=breakeven,
        best_case=best,
        worst_case=worst,
        sharpe_sensitivity_to_fees=fee_sens,
        sharpe_sensitivity_to_slippage=slip_sens,
    )
