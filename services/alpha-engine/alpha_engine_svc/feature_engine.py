"""Rolling feature computation engine.

Computes real-time features from the tick stream for use by strategies.
This is the Python implementation — will be swapped for C++ in Phase 6.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Features:
    """Snapshot of computed features at a point in time."""

    timestamp: int = 0
    symbol: str = ""
    vwap: float = 0.0
    trade_imbalance: float = 0.0  # buy vs sell pressure
    volatility: float = 0.0  # rolling std of returns
    trade_rate: float = 0.0  # trades per second
    mid_price: float | None = None
    spread: float | None = None
    book_imbalance: float = 0.0


class FeatureEngine:
    """Computes rolling features from trade and book data.

    Interface contract (preserved when migrating to C++):
        - on_trade(price, quantity, is_buyer_maker, timestamp_ms) -> None
        - on_book_snapshot(mid_price, spread, imbalance) -> None
        - compute() -> Features
    """

    def __init__(self, symbol: str, window_size: int = 100):
        self.symbol = symbol
        self._window_size = window_size
        self._prices: deque[float] = deque(maxlen=window_size)
        self._quantities: deque[float] = deque(maxlen=window_size)
        self._sides: deque[bool] = deque(maxlen=window_size)  # True = buyer maker
        self._timestamps: deque[int] = deque(maxlen=window_size)
        self._pv_sum: float = 0.0  # price * volume running sum
        self._v_sum: float = 0.0  # volume running sum

        # Latest book state
        self._mid_price: float | None = None
        self._spread: float | None = None
        self._book_imbalance: float = 0.0

    def on_trade(self, price: float, quantity: float, is_buyer_maker: bool, timestamp_ms: int) -> None:
        """Ingest a new trade tick."""
        # Evict oldest if at capacity
        if len(self._prices) == self._window_size:
            old_p = self._prices[0]
            old_q = self._quantities[0]
            self._pv_sum -= old_p * old_q
            self._v_sum -= old_q

        self._prices.append(price)
        self._quantities.append(quantity)
        self._sides.append(is_buyer_maker)
        self._timestamps.append(timestamp_ms)
        self._pv_sum += price * quantity
        self._v_sum += quantity

    def on_book_snapshot(self, mid_price: float | None, spread: float | None, imbalance: float) -> None:
        """Update latest book state."""
        self._mid_price = mid_price
        self._spread = spread
        self._book_imbalance = imbalance

    def compute(self) -> Features:
        """Compute current feature snapshot."""
        n = len(self._prices)
        if n == 0:
            return Features(symbol=self.symbol)

        # VWAP
        vwap = self._pv_sum / self._v_sum if self._v_sum > 0 else 0.0

        # Trade imbalance: ratio of sell-initiated vs buy-initiated volume
        buy_vol = sum(q for q, s in zip(self._quantities, self._sides, strict=True) if s)
        sell_vol = sum(q for q, s in zip(self._quantities, self._sides, strict=True) if not s)
        total_vol = buy_vol + sell_vol
        trade_imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0.0

        # Volatility: std of log returns
        volatility = 0.0
        if n >= 2:
            returns = []
            prices = list(self._prices)
            for i in range(1, n):
                if prices[i - 1] > 0:
                    returns.append(prices[i] / prices[i - 1] - 1.0)
            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                volatility = variance**0.5

        # Trade rate (trades per second over window)
        trade_rate = 0.0
        if n >= 2:
            time_span_s = (self._timestamps[-1] - self._timestamps[0]) / 1000.0
            if time_span_s > 0:
                trade_rate = n / time_span_s

        return Features(
            timestamp=self._timestamps[-1] if self._timestamps else 0,
            symbol=self.symbol,
            vwap=vwap,
            trade_imbalance=trade_imbalance,
            volatility=volatility,
            trade_rate=trade_rate,
            mid_price=self._mid_price,
            spread=self._spread,
            book_imbalance=self._book_imbalance,
        )
