"""Risk-adjusted return metrics.

Computes Sharpe, Sortino, Calmar, max drawdown, and other performance
metrics from a series of PnL snapshots.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Annualization factor for crypto (365 days, 24/7)
ANNUAL_FACTOR = 365.0


@dataclass
class PerformanceMetrics:
    """Computed performance metrics over a period."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_hours: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    num_trades: int = 0


def compute_sharpe(returns: list[float], risk_free_daily: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns) - risk_free_daily
    std = _std(returns)
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(ANNUAL_FACTOR)


def compute_sortino(returns: list[float], risk_free_daily: float = 0.0) -> float:
    """Annualized Sortino ratio (penalizes only downside volatility)."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns) - risk_free_daily
    downside = [r for r in returns if r < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    downside_std = _std(downside)
    if downside_std == 0.0:
        return 0.0
    return (mean / downside_std) * math.sqrt(ANNUAL_FACTOR)


def compute_max_drawdown(equity_curve: list[float]) -> tuple[float, int]:
    """Max drawdown and duration (in number of periods).

    Returns (max_drawdown_fraction, max_duration_periods).
    """
    if not equity_curve:
        return 0.0, 0

    peak = equity_curve[0]
    max_dd = 0.0
    max_duration = 0
    current_duration = 0

    for value in equity_curve:
        if value >= peak:
            peak = value
            current_duration = 0
        else:
            dd = (peak - value) / peak
            max_dd = max(max_dd, dd)
            current_duration += 1
            max_duration = max(max_duration, current_duration)

    return max_dd, max_duration


def compute_calmar(annualized_return: float, max_drawdown: float) -> float:
    """Calmar ratio: annualized return / max drawdown."""
    if max_drawdown == 0.0:
        return 0.0
    return annualized_return / max_drawdown


def _std(values: list[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance ** 0.5
