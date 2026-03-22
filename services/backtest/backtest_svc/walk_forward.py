"""Walk-forward optimization.

Splits a trade sequence into rolling train/test windows, optimizes strategy
parameters on each training fold, and evaluates on the subsequent test fold.
This gives a realistic estimate of out-of-sample performance while adapting
to regime changes over time.

Window types:
    - Rolling: fixed-size train window slides forward
    - Expanding: train window grows from the start, test window slides
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class WindowType(StrEnum):
    ROLLING = "rolling"
    EXPANDING = "expanding"


@dataclass
class WalkForwardConfig:
    """Configuration for walk-forward analysis."""

    n_splits: int = 5  # number of train/test folds
    train_pct: float = 0.7  # fraction of each fold used for training
    window_type: WindowType = WindowType.ROLLING
    min_train_size: int = 50  # minimum trades in training set
    min_test_size: int = 20  # minimum trades in test set


@dataclass
class FoldResult:
    """Metrics from a single train/test fold."""

    fold_index: int = 0
    train_start: int = 0
    train_end: int = 0
    test_start: int = 0
    test_end: int = 0
    best_params: dict[str, Any] = field(default_factory=dict)
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    train_return: float = 0.0
    test_return: float = 0.0
    train_max_drawdown: float = 0.0
    test_max_drawdown: float = 0.0
    num_train_trades: int = 0
    num_test_trades: int = 0


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward results."""

    folds: list[FoldResult] = field(default_factory=list)
    mean_test_sharpe: float = 0.0
    std_test_sharpe: float = 0.0
    mean_test_return: float = 0.0
    mean_test_drawdown: float = 0.0
    overfitting_ratio: float = 0.0  # mean(train_sharpe) / mean(test_sharpe)
    degradation_pct: float = 0.0  # (train - test) / train as percentage


class StrategyEvaluator(Protocol):
    """Protocol for strategy evaluation on a trade sequence.

    Implementations run a strategy over a set of trades and return
    performance metrics. The backtest engine plugs into this interface.
    """

    def evaluate(
        self,
        trades: list[dict],
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Run strategy on trades with given params.

        Returns dict with at minimum: 'sharpe', 'total_return', 'max_drawdown'.
        """
        ...


def generate_folds(
    n_trades: int,
    config: WalkForwardConfig,
) -> list[tuple[int, int, int, int]]:
    """Generate (train_start, train_end, test_start, test_end) index tuples.

    Returns a list of fold boundaries. Each tuple defines inclusive start
    and exclusive end indices into the trade list.
    """
    if n_trades == 0:
        return []

    folds = []
    n_splits = config.n_splits

    if config.window_type == WindowType.ROLLING:
        # Equal-sized chunks, sliding forward
        fold_size = n_trades / n_splits
        train_size = int(fold_size * config.train_pct)
        test_size = int(fold_size * (1 - config.train_pct))

        if train_size < config.min_train_size or test_size < config.min_test_size:
            # Fall back to fewer splits
            n_splits = max(
                1,
                n_trades // (config.min_train_size + config.min_test_size),
            )
            if n_splits == 0:
                return []
            fold_size = n_trades / n_splits
            train_size = int(fold_size * config.train_pct)
            test_size = int(fold_size * (1 - config.train_pct))

        step = (n_trades - train_size - test_size) / max(n_splits - 1, 1)

        for i in range(n_splits):
            start = int(i * step)
            train_start = start
            train_end = start + train_size
            test_start = train_end
            test_end = min(test_start + test_size, n_trades)

            if test_end <= test_start:
                break

            folds.append((train_start, train_end, test_start, test_end))

    elif config.window_type == WindowType.EXPANDING:
        # Training window grows, test window slides
        test_size = max(
            config.min_test_size,
            n_trades // (n_splits + 1),
        )
        initial_train = max(
            config.min_train_size,
            n_trades - n_splits * test_size,
        )

        for i in range(n_splits):
            train_start = 0
            test_start = initial_train + i * test_size
            train_end = test_start
            test_end = min(test_start + test_size, n_trades)

            if train_end >= n_trades or test_end <= test_start:
                break

            folds.append((train_start, train_end, test_start, test_end))

    return folds


def run_walk_forward(
    trades: list[dict],
    evaluator: StrategyEvaluator,
    param_grid: list[dict[str, Any]],
    config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Execute walk-forward optimization.

    For each fold:
    1. Optimize parameters on training data (best Sharpe across param_grid)
    2. Evaluate best params on test data
    3. Record train vs test performance for overfitting detection

    Args:
        trades: Full list of trade dicts (chronological order).
        evaluator: Strategy evaluator implementing the StrategyEvaluator protocol.
        param_grid: List of parameter combinations to search.
        config: Walk-forward configuration (uses defaults if None).

    Returns:
        WalkForwardResult with per-fold and aggregate metrics.
    """
    if config is None:
        config = WalkForwardConfig()

    folds_indices = generate_folds(len(trades), config)
    if not folds_indices:
        return WalkForwardResult()

    fold_results: list[FoldResult] = []

    for fold_idx, (train_start, train_end, test_start, test_end) in enumerate(folds_indices):
        train_data = trades[train_start:train_end]
        test_data = trades[test_start:test_end]

        # Optimize on training data
        best_params: dict[str, Any] = {}
        best_train_sharpe = -math.inf
        best_train_metrics: dict[str, float] = {}

        for params in param_grid:
            metrics = evaluator.evaluate(train_data, params)
            sharpe = metrics.get("sharpe", 0.0)
            if sharpe > best_train_sharpe:
                best_train_sharpe = sharpe
                best_params = params
                best_train_metrics = metrics

        # Evaluate on test data with best params
        test_metrics = evaluator.evaluate(test_data, best_params)

        fold_result = FoldResult(
            fold_index=fold_idx,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            best_params=best_params,
            train_sharpe=best_train_metrics.get("sharpe", 0.0),
            test_sharpe=test_metrics.get("sharpe", 0.0),
            train_return=best_train_metrics.get("total_return", 0.0),
            test_return=test_metrics.get("total_return", 0.0),
            train_max_drawdown=best_train_metrics.get("max_drawdown", 0.0),
            test_max_drawdown=test_metrics.get("max_drawdown", 0.0),
            num_train_trades=len(train_data),
            num_test_trades=len(test_data),
        )
        fold_results.append(fold_result)

        logger.info(
            "Fold %d: train_sharpe=%.3f test_sharpe=%.3f params=%s",
            fold_idx,
            fold_result.train_sharpe,
            fold_result.test_sharpe,
            best_params,
        )

    # Aggregate
    result = WalkForwardResult(folds=fold_results)

    if fold_results:
        test_sharpes = [f.test_sharpe for f in fold_results]
        train_sharpes = [f.train_sharpe for f in fold_results]

        result.mean_test_sharpe = sum(test_sharpes) / len(test_sharpes)
        result.mean_test_return = sum(f.test_return for f in fold_results) / len(fold_results)
        result.mean_test_drawdown = sum(f.test_max_drawdown for f in fold_results) / len(fold_results)

        if len(test_sharpes) > 1:
            mean = result.mean_test_sharpe
            result.std_test_sharpe = (sum((s - mean) ** 2 for s in test_sharpes) / len(test_sharpes)) ** 0.5

        mean_train = sum(train_sharpes) / len(train_sharpes)
        if result.mean_test_sharpe != 0:
            result.overfitting_ratio = mean_train / result.mean_test_sharpe

        if mean_train != 0:
            result.degradation_pct = (mean_train - result.mean_test_sharpe) / abs(mean_train) * 100.0

    return result
