"""Parameter sensitivity analysis.

Grid search and random search over strategy parameters to map the
performance surface. Identifies which parameters have the strongest
effect on returns/Sharpe and detects fragile configurations where
small parameter changes cause large performance swings.
"""

from __future__ import annotations

import itertools
import logging
import math
import random as rand_mod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SearchMethod(StrEnum):
    GRID = "grid"
    RANDOM = "random"


@dataclass
class ParamRange:
    """Defines the search space for a single parameter."""

    name: str
    values: list[Any] = field(default_factory=list)  # for grid search
    low: float = 0.0  # for random search
    high: float = 1.0  # for random search
    log_scale: bool = False  # sample in log space for random search
    dtype: str = "float"  # "float" or "int"


@dataclass
class SensitivityPoint:
    """Result of evaluating one parameter combination."""

    params: dict[str, Any] = field(default_factory=dict)
    sharpe: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ParamImpact:
    """How much a single parameter affects performance."""

    param_name: str = ""
    correlation_with_sharpe: float = 0.0
    best_value: Any = None
    worst_value: Any = None
    sharpe_range: float = 0.0  # max - min sharpe across values


@dataclass
class SensitivityResult:
    """Full sensitivity analysis output."""

    points: list[SensitivityPoint] = field(default_factory=list)
    best_params: dict[str, Any] = field(default_factory=dict)
    best_sharpe: float = 0.0
    param_impacts: list[ParamImpact] = field(default_factory=list)
    search_method: SearchMethod = SearchMethod.GRID
    num_evaluations: int = 0


class StrategyEvaluator(Protocol):
    """Protocol for strategy evaluation."""

    def evaluate(
        self,
        trades: list[dict],
        params: dict[str, Any],
    ) -> dict[str, float]: ...


def build_grid(param_ranges: list[ParamRange]) -> list[dict[str, Any]]:
    """Build a full Cartesian grid from parameter ranges."""
    if not param_ranges:
        return [{}]

    names = [p.name for p in param_ranges]
    value_lists = [p.values for p in param_ranges]

    grid = []
    for combo in itertools.product(*value_lists):
        grid.append(dict(zip(names, combo, strict=True)))

    return grid


def build_random_samples(
    param_ranges: list[ParamRange],
    n_samples: int = 50,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Generate random parameter combinations from ranges."""
    rng = rand_mod.Random(seed)
    samples = []

    for _ in range(n_samples):
        combo: dict[str, Any] = {}
        for p in param_ranges:
            if p.values:
                # Pick from explicit values
                combo[p.name] = rng.choice(p.values)
            elif p.log_scale:
                log_low = math.log(max(p.low, 1e-10))
                log_high = math.log(max(p.high, 1e-10))
                val = math.exp(rng.uniform(log_low, log_high))
                combo[p.name] = round(val) if p.dtype == "int" else val
            else:
                val = rng.uniform(p.low, p.high)
                combo[p.name] = round(val) if p.dtype == "int" else val
        samples.append(combo)

    return samples


def compute_param_impacts(
    points: list[SensitivityPoint],
    param_names: list[str],
) -> list[ParamImpact]:
    """Compute per-parameter impact on Sharpe ratio.

    For each parameter, groups results by parameter value and computes
    how strongly the parameter correlates with Sharpe variation.
    """
    impacts = []

    for name in param_names:
        # Group sharpe values by parameter value
        groups: dict[Any, list[float]] = {}
        for pt in points:
            val = pt.params.get(name)
            if val is not None:
                groups.setdefault(val, []).append(pt.sharpe)

        if not groups:
            continue

        # Mean sharpe per value
        mean_sharpes = {v: sum(s) / len(s) for v, s in groups.items()}
        all_sharpes = list(mean_sharpes.values())

        best_val = max(mean_sharpes, key=lambda v: mean_sharpes[v])
        worst_val = min(mean_sharpes, key=lambda v: mean_sharpes[v])

        sharpe_range = max(all_sharpes) - min(all_sharpes) if all_sharpes else 0.0

        # Simple correlation: Pearson between numeric param values and sharpe
        corr = 0.0
        try:
            numeric_vals = [float(v) for v in mean_sharpes]
            sharpe_vals = [mean_sharpes[v] for v in mean_sharpes]
            corr = _pearson(numeric_vals, sharpe_vals)
        except ValueError, TypeError:
            pass

        impacts.append(
            ParamImpact(
                param_name=name,
                correlation_with_sharpe=corr,
                best_value=best_val,
                worst_value=worst_val,
                sharpe_range=sharpe_range,
            )
        )

    # Sort by impact (sharpe_range descending)
    impacts.sort(key=lambda i: i.sharpe_range, reverse=True)
    return impacts


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True)) / n
    sx = (sum((xi - mx) ** 2 for xi in x) / n) ** 0.5
    sy = (sum((yi - my) ** 2 for yi in y) / n) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def run_sensitivity(
    trades: list[dict],
    evaluator: StrategyEvaluator,
    param_ranges: list[ParamRange],
    method: SearchMethod = SearchMethod.GRID,
    n_random_samples: int = 50,
    random_seed: int | None = None,
) -> SensitivityResult:
    """Run parameter sensitivity analysis.

    Args:
        trades: Trade data for evaluation.
        evaluator: Strategy evaluator.
        param_ranges: Parameter search spaces.
        method: GRID or RANDOM search.
        n_random_samples: Number of samples for random search.
        random_seed: Seed for reproducibility in random search.

    Returns:
        SensitivityResult with all evaluation points and impact analysis.
    """
    if method == SearchMethod.GRID:
        param_combos = build_grid(param_ranges)
    else:
        param_combos = build_random_samples(param_ranges, n_samples=n_random_samples, seed=random_seed)

    points: list[SensitivityPoint] = []
    best_sharpe = -math.inf
    best_params: dict[str, Any] = {}

    for i, params in enumerate(param_combos):
        metrics = evaluator.evaluate(trades, params)
        sharpe = metrics.get("sharpe", 0.0)

        point = SensitivityPoint(
            params=params,
            sharpe=sharpe,
            total_return=metrics.get("total_return", 0.0),
            max_drawdown=metrics.get("max_drawdown", 0.0),
            num_trades=int(metrics.get("num_trades", 0)),
            metrics=metrics,
        )
        points.append(point)

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_params = params

        if (i + 1) % 50 == 0:
            logger.info("Evaluated %d/%d parameter combinations", i + 1, len(param_combos))

    param_names = [p.name for p in param_ranges]
    impacts = compute_param_impacts(points, param_names)

    return SensitivityResult(
        points=points,
        best_params=best_params,
        best_sharpe=best_sharpe,
        param_impacts=impacts,
        search_method=method,
        num_evaluations=len(points),
    )
