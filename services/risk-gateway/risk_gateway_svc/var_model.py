"""Parametric Value-at-Risk using Geometric Brownian Motion.

Models the portfolio value as a GBM process and estimates VaR
at a given confidence level over a specified time horizon.

VaR_a = P * (1 - exp(mu*dt - z_a * sigma * sqrt(dt)))

Where:
    P     = current portfolio value
    mu    = drift (estimated from rolling returns)
    sigma = volatility (estimated from rolling returns)
    dt    = time horizon in days
    z_a   = z-score for confidence level a
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Standard normal quantiles
Z_SCORES = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.99: 2.3263,
}


@dataclass
class VaRResult:
    """VaR computation result."""

    var_amount: float = 0.0  # dollar amount at risk
    var_pct: float = 0.0  # as percentage of portfolio
    confidence: float = 0.95
    horizon_hours: float = 1.0
    volatility: float = 0.0  # annualized
    drift: float = 0.0  # annualized
    n_observations: int = 0


class ParametricVaR:
    """Estimates Value-at-Risk using GBM-based parametric model.

    Consumes price observations and computes rolling volatility.
    """

    def __init__(
        self,
        window_size: int = 1000,
        confidence: float = 0.95,
        horizon_hours: float = 1.0,
    ):
        self._window_size = window_size
        self._confidence = confidence
        self._horizon_hours = horizon_hours
        self._prices: deque[float] = deque(maxlen=window_size)
        self._timestamps: deque[int] = deque(maxlen=window_size)

    def update(self, price: float, timestamp_ms: int) -> None:
        """Ingest a new price observation."""
        self._prices.append(price)
        self._timestamps.append(timestamp_ms)

    def compute(self, portfolio_value: float) -> VaRResult:
        """Compute VaR for the current portfolio value.

        Returns VaRResult with the estimated loss at the configured
        confidence level over the configured horizon.
        """
        n = len(self._prices)
        if n < 10:
            return VaRResult(
                confidence=self._confidence,
                horizon_hours=self._horizon_hours,
                n_observations=n,
            )

        # Compute log returns
        log_returns = []
        prices = list(self._prices)
        for i in range(1, n):
            if prices[i - 1] > 0 and prices[i] > 0:
                log_returns.append(math.log(prices[i] / prices[i - 1]))

        if len(log_returns) < 5:
            return VaRResult(
                confidence=self._confidence,
                horizon_hours=self._horizon_hours,
                n_observations=n,
            )

        # Estimate per-observation drift and volatility
        mean_return = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_return) ** 2 for r in log_returns) / len(log_returns)
        vol_per_obs = variance**0.5

        # Estimate observation frequency to annualize
        timestamps = list(self._timestamps)
        total_time_ms = timestamps[-1] - timestamps[0]
        if total_time_ms <= 0:
            return VaRResult(
                confidence=self._confidence,
                horizon_hours=self._horizon_hours,
                n_observations=n,
            )

        obs_per_hour = (n - 1) / (total_time_ms / 3_600_000)

        # Annualize (crypto = 365 * 24 hours)
        hours_per_year = 365.0 * 24.0
        annual_vol = vol_per_obs * math.sqrt(obs_per_hour * hours_per_year)
        annual_drift = mean_return * obs_per_hour * hours_per_year

        # Scale to horizon
        dt = self._horizon_hours / hours_per_year
        vol_horizon = annual_vol * math.sqrt(dt)
        drift_horizon = annual_drift * dt

        # Get z-score for confidence level
        z = Z_SCORES.get(self._confidence, 1.6449)

        # VaR under GBM: P * (1 - exp(drift - z * vol))
        var_pct = 1.0 - math.exp(drift_horizon - z * vol_horizon)
        var_amount = portfolio_value * var_pct

        return VaRResult(
            var_amount=max(var_amount, 0.0),
            var_pct=max(var_pct, 0.0),
            confidence=self._confidence,
            horizon_hours=self._horizon_hours,
            volatility=annual_vol,
            drift=annual_drift,
            n_observations=n,
        )
