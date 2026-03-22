"""Linear regression fair value strategy.

Estimates a short-term fair price by regressing recent price against
features (order book imbalance, trade flow, volume), then trades the
residual when the market price diverges from the predicted fair value.

The regression is fit on a rolling window and re-estimated every N trades.
The signal strength is proportional to the z-score of the residual.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from alpha_engine_svc.feature_engine import FeatureEngine
from alpha_engine_svc.strategy import BaseStrategy
from quant_core.models import DepthUpdate, Signal, Trade, now_ms

logger = logging.getLogger(__name__)

DEFAULT_PARAMS = {
    "window_size": 200,  # trades in rolling window
    "refit_interval": 50,  # re-estimate regression every N trades
    "threshold_std": 1.5,  # residual z-score to trigger signal
    "warmup_trades": 100,  # minimum trades before generating signals
    "base_quantity": 0.001,
    "cooldown_trades": 20,
}


def _ols_fit(x_mat: list[list[float]], y: list[float]) -> tuple[list[float], float]:
    """Ordinary least squares via normal equations.

    Fits y = X @ beta + intercept.
    Returns (beta_coefficients, intercept).

    Uses manual matrix math to avoid numpy dependency in the hot path.
    """
    n = len(y)
    if n == 0:
        return [], 0.0

    k = len(x_mat[0]) if x_mat else 0

    # Add intercept column: x_aug = [X | 1]
    x_aug = [[*row, 1.0] for row in x_mat]
    cols = k + 1

    # X^T @ X
    xtx = [[0.0] * cols for _ in range(cols)]
    for row in x_aug:
        for i in range(cols):
            for j in range(cols):
                xtx[i][j] += row[i] * row[j]

    # X^T @ y
    xty = [0.0] * cols
    for i, row in enumerate(x_aug):
        for j in range(cols):
            xty[j] += row[j] * y[i]

    # Solve via Gaussian elimination
    beta = _solve_linear_system(xtx, xty)
    if beta is None:
        return [], 0.0

    return beta[:k], beta[k]


def _solve_linear_system(a_mat: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve Ax = b via Gaussian elimination with partial pivoting."""
    n = len(b)
    # Augmented matrix
    aug = [[*a_mat[i][:], b[i]] for i in range(n)]

    for col in range(n):
        # Partial pivot
        max_row = col
        for row in range(col + 1, n):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]

        if abs(aug[col][col]) < 1e-4:
            return None  # singular

        # Eliminate below
        for row in range(col + 1, n):
            factor = aug[row][col] / aug[col][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        x[i] /= aug[i][i]

    return x


def _predict(x_row: list[float], beta: list[float], intercept: float) -> float:
    """Predict y from a single feature row."""
    return sum(x * b for x, b in zip(x_row, beta, strict=True)) + intercept


class LinearRegressionStrategy(BaseStrategy):
    """Trade residuals from a rolling OLS fair value model."""

    def __init__(
        self,
        strategy_id: str = "linear_regression_v1",
        symbol: str = "BTCUSD",
        params: dict[str, Any] | None = None,
    ):
        merged = {**DEFAULT_PARAMS, **(params or {})}
        super().__init__(strategy_id=strategy_id, symbol=symbol, params=merged)

        self._feature_engine = FeatureEngine(
            symbol=symbol,
            window_size=merged["window_size"],
        )
        self._trade_count = 0
        self._trades_since_last_signal = 0
        self._trades_since_last_fit = 0
        self._last_signal_side: str | None = None

        # Rolling data for regression
        ws = merged["window_size"]
        self._feature_history: deque[list[float]] = deque(maxlen=ws)
        self._price_history: deque[float] = deque(maxlen=ws)

        # Current model
        self._beta: list[float] = []
        self._intercept: float = 0.0
        self._residual_std: float = 0.0
        self._model_fitted: bool = False

        # Book state
        self._mid_price: float | None = None
        self._spread: float | None = None
        self._book_imbalance: float = 0.0

    @property
    def is_warmed_up(self) -> bool:
        return self._trade_count >= self.params["warmup_trades"]

    @property
    def cooldown_elapsed(self) -> bool:
        return self._trades_since_last_signal >= self.params["cooldown_trades"]

    def _build_feature_row(self) -> list[float]:
        """Build feature vector for current state."""
        features = self._feature_engine.compute()
        return [
            features.vwap,
            features.trade_imbalance,
            features.volatility * 10000,  # scale up for numerical stability
            self._book_imbalance,
        ]

    def _fit_model(self) -> None:
        """Re-estimate the regression model on current window."""
        if len(self._price_history) < 20:
            return

        x_mat = list(self._feature_history)
        y = list(self._price_history)

        beta, intercept = _ols_fit(x_mat, y)
        if not beta:
            return

        # Compute residual std
        residuals = []
        for x_i, yi in zip(x_mat, y, strict=True):
            pred = _predict(x_i, beta, intercept)
            residuals.append(yi - pred)

        n = len(residuals)
        if n < 2:
            return

        mean_r = sum(residuals) / n
        var_r = sum((r - mean_r) ** 2 for r in residuals) / n
        std_r = var_r**0.5

        if std_r > 0:
            self._beta = beta
            self._intercept = intercept
            self._residual_std = std_r
            self._model_fitted = True
            self._trades_since_last_fit = 0

    def on_trade(self, trade: Trade) -> Signal | None:
        self._trade_count += 1
        self._trades_since_last_signal += 1
        self._trades_since_last_fit += 1

        self._feature_engine.on_trade(
            price=trade.price,
            quantity=trade.quantity,
            is_buyer_maker=trade.is_buyer_maker,
            timestamp_ms=trade.timestamp_exchange,
        )

        # Store feature + price for regression
        feature_row = self._build_feature_row()
        self._feature_history.append(feature_row)
        self._price_history.append(trade.price)

        # Periodically refit
        if self._trades_since_last_fit >= self.params["refit_interval"]:
            self._fit_model()

        if not self.is_warmed_up or not self._model_fitted:
            return None

        if not self.cooldown_elapsed:
            return None

        # Predict fair value and compute residual
        fair_value = _predict(feature_row, self._beta, self._intercept)
        residual = trade.price - fair_value

        if self._residual_std == 0:
            return None

        z_score = residual / self._residual_std
        threshold = self.params["threshold_std"]

        side = None
        strength = 0.0

        if z_score < -threshold:
            side = "BUY"
            strength = min(abs(z_score) / (threshold * 2), 1.0)
        elif z_score > threshold:
            side = "SELL"
            strength = min(abs(z_score) / (threshold * 2), 1.0)

        if side is None:
            return None

        if side == self._last_signal_side:
            return None

        self._last_signal_side = side
        self._trades_since_last_signal = 0

        return Signal(
            timestamp=now_ms(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            side=side,
            strength=strength,
            target_quantity=self.params["base_quantity"],
            urgency=min(strength, 1.0),
            mid_price_at_signal=self._mid_price or trade.price,
            spread_at_signal=self._spread or 0.0,
            metadata={
                "z_score": round(z_score, 4),
                "fair_value": round(fair_value, 2),
                "residual": round(residual, 4),
                "residual_std": round(self._residual_std, 6),
                "n_features": len(self._beta),
            },
        )

    def on_book_update(self, update: DepthUpdate) -> Signal | None:
        if update.bids and update.asks:
            best_bid = max(b[0] for b in update.bids) if update.bids else None
            best_ask = min(a[0] for a in update.asks) if update.asks else None
            if best_bid and best_ask:
                self._mid_price = (best_bid + best_ask) / 2.0
                self._spread = best_ask - best_bid

                bid_vol = sum(b[1] for b in update.bids)
                ask_vol = sum(a[1] for a in update.asks)
                total = bid_vol + ask_vol
                self._book_imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0

        self._feature_engine.on_book_snapshot(
            mid_price=self._mid_price,
            spread=self._spread,
            imbalance=self._book_imbalance,
        )
        return None
