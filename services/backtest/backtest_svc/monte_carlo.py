"""Monte Carlo simulation for backtest confidence intervals.

Resamples trade sequences with replacement (bootstrap) to estimate
the distribution of performance metrics like Sharpe ratio and max
drawdown. Provides confidence intervals so you know whether an
observed Sharpe of 2.0 might just be luck.

Methods:
    - Bootstrap resampling: shuffle trade returns with replacement
    - Block bootstrap: preserve autocorrelation by resampling blocks
"""

from __future__ import annotations

import logging
import math
import random as rand_mod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0 * 1000.0
HOUR_MS = 60 * 60 * 1000


@dataclass
class MonteCarloConfig:
    """Configuration for Monte Carlo simulation."""

    n_simulations: int = 1000
    block_size: int = 1  # 1 = standard bootstrap, >1 = block bootstrap
    confidence_levels: list[float] = field(default_factory=lambda: [0.05, 0.25, 0.50, 0.75, 0.95])
    seed: int | None = None


@dataclass
class ConfidenceInterval:
    """A single confidence interval for a metric."""

    level: float = 0.0
    value: float = 0.0


@dataclass
class MetricDistribution:
    """Distribution of a metric across simulations."""

    metric_name: str = ""
    mean: float = 0.0
    std: float = 0.0
    median: float = 0.0
    confidence_intervals: list[ConfidenceInterval] = field(default_factory=list)
    simulated_values: list[float] = field(default_factory=list)


@dataclass
class MonteCarloResult:
    """Full Monte Carlo simulation output."""

    n_simulations: int = 0
    observed_sharpe: float = 0.0
    observed_max_drawdown: float = 0.0
    observed_total_return: float = 0.0
    sharpe_distribution: MetricDistribution = field(default_factory=MetricDistribution)
    drawdown_distribution: MetricDistribution = field(default_factory=MetricDistribution)
    return_distribution: MetricDistribution = field(default_factory=MetricDistribution)
    prob_positive_sharpe: float = 0.0  # P(Sharpe > 0)
    prob_sharpe_above_1: float = 0.0  # P(Sharpe > 1)


def _compute_returns(equity_curve: list[float]) -> list[float]:
    """Compute period-over-period returns from equity curve."""
    if len(equity_curve) < 2:
        return []
    return [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] if equity_curve[i - 1] != 0 else 0.0
        for i in range(1, len(equity_curve))
    ]


def _sharpe_from_returns(returns: list[float], bucket_ms: int = HOUR_MS) -> float:
    """Annualized Sharpe from a bucketed return series.

    `bucket_ms` is the time span each return represents. Annualization is
    sqrt(buckets_per_year). Using hourly returns → sqrt(8760).
    """
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = var**0.5
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(MS_PER_YEAR / bucket_ms)


def _max_drawdown_from_returns(returns: list[float]) -> float:
    """Max drawdown from a return series."""
    if not returns:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _total_return_from_returns(returns: list[float]) -> float:
    """Cumulative return from a return series."""
    if not returns:
        return 0.0
    cum = 1.0
    for r in returns:
        cum *= 1 + r
    return cum - 1.0


def _build_distribution(
    values: list[float],
    metric_name: str,
    confidence_levels: list[float],
) -> MetricDistribution:
    """Build a MetricDistribution from simulated values."""
    if not values:
        return MetricDistribution(metric_name=metric_name)

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean = sum(sorted_vals) / n
    var = sum((v - mean) ** 2 for v in sorted_vals) / n
    std = var**0.5
    median = sorted_vals[n // 2]

    cis = []
    for level in confidence_levels:
        idx = max(0, min(int(level * n), n - 1))
        cis.append(ConfidenceInterval(level=level, value=sorted_vals[idx]))

    return MetricDistribution(
        metric_name=metric_name,
        mean=mean,
        std=std,
        median=median,
        confidence_intervals=cis,
        simulated_values=values,
    )


def _resample_returns(
    returns: list[float],
    rng: rand_mod.Random,
    block_size: int = 1,
) -> list[float]:
    """Resample returns using bootstrap or block bootstrap."""
    n = len(returns)
    if n == 0:
        return []

    if block_size <= 1:
        # Standard bootstrap: sample with replacement
        return [returns[rng.randint(0, n - 1)] for _ in range(n)]

    # Block bootstrap
    resampled: list[float] = []
    while len(resampled) < n:
        start = rng.randint(0, n - 1)
        for j in range(block_size):
            if len(resampled) >= n:
                break
            idx = (start + j) % n  # wrap around
            resampled.append(returns[idx])

    return resampled[:n]


def run_monte_carlo(
    equity_curve: list[float],
    config: MonteCarloConfig | None = None,
    bucket_ms: int = HOUR_MS,
) -> MonteCarloResult:
    """Run Monte Carlo simulation on an equity curve.

    Bootstrap resamples the return series to estimate the distribution
    of Sharpe ratio, max drawdown, and total return.

    Args:
        equity_curve: Time series of portfolio equity values, where each
            adjacent pair represents one bucket of duration `bucket_ms`.
        config: Simulation configuration (uses defaults if None).
        bucket_ms: Time span each equity point represents. Used to annualize
            Sharpe correctly. Defaults to 1 hour.

    Returns:
        MonteCarloResult with distributions and confidence intervals.
    """
    if config is None:
        config = MonteCarloConfig()

    returns = _compute_returns(equity_curve)
    if not returns:
        return MonteCarloResult()

    # Observed metrics
    observed_sharpe = _sharpe_from_returns(returns, bucket_ms)
    observed_dd = _max_drawdown_from_returns(returns)
    observed_ret = _total_return_from_returns(returns)

    rng = rand_mod.Random(config.seed)

    sim_sharpes: list[float] = []
    sim_drawdowns: list[float] = []
    sim_returns: list[float] = []

    for i in range(config.n_simulations):
        resampled = _resample_returns(returns, rng, config.block_size)
        sim_sharpes.append(_sharpe_from_returns(resampled, bucket_ms))
        sim_drawdowns.append(_max_drawdown_from_returns(resampled))
        sim_returns.append(_total_return_from_returns(resampled))

        if (i + 1) % 500 == 0:
            logger.info("Monte Carlo: %d/%d simulations", i + 1, config.n_simulations)

    result = MonteCarloResult(
        n_simulations=config.n_simulations,
        observed_sharpe=observed_sharpe,
        observed_max_drawdown=observed_dd,
        observed_total_return=observed_ret,
        sharpe_distribution=_build_distribution(sim_sharpes, "sharpe", config.confidence_levels),
        drawdown_distribution=_build_distribution(sim_drawdowns, "max_drawdown", config.confidence_levels),
        return_distribution=_build_distribution(sim_returns, "total_return", config.confidence_levels),
    )

    if sim_sharpes:
        result.prob_positive_sharpe = sum(1 for s in sim_sharpes if s > 0) / len(sim_sharpes)
        result.prob_sharpe_above_1 = sum(1 for s in sim_sharpes if s > 1) / len(sim_sharpes)

    return result
