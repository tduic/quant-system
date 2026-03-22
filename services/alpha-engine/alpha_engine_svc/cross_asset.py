"""Cross-asset analytics: rolling correlation and relative strength.

Maintains per-symbol price histories and computes pairwise metrics
for use by multi-asset strategies (e.g., pairs trading).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default rolling window for correlation/relative-strength calculations
DEFAULT_WINDOW = 100
MIN_OBSERVATIONS = 20  # minimum data points before computing metrics


@dataclass
class CrossAssetSnapshot:
    """Point-in-time cross-asset metrics for a symbol pair."""

    symbol_a: str = ""
    symbol_b: str = ""
    correlation: float | None = None
    relative_strength: float | None = None  # return_a / return_b over window
    spread_z_score: float | None = None  # z-score of log price ratio
    timestamp_ms: int = 0


class CrossAssetTracker:
    """Tracks rolling cross-asset relationships between symbols.

    Maintains a deque of (timestamp_ms, price) per symbol and computes:
    - Pearson correlation of log returns between symbol pairs
    - Relative strength (cumulative return ratio)
    - Z-score of the log price ratio (for mean-reversion pairs)
    """

    def __init__(self, window: int = DEFAULT_WINDOW):
        self._window = window
        # symbol -> deque of (timestamp_ms, price)
        self._prices: dict[str, deque[tuple[int, float]]] = {}

    @property
    def symbols(self) -> list[str]:
        """Return tracked symbols."""
        return list(self._prices.keys())

    def on_price(self, symbol: str, timestamp_ms: int, price: float) -> None:
        """Record a new price observation for a symbol."""
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self._window + 1)
        self._prices[symbol].append((timestamp_ms, price))

    def get_snapshot(self, symbol_a: str, symbol_b: str) -> CrossAssetSnapshot:
        """Compute cross-asset metrics for a pair of symbols."""
        ts = 0
        prices_a = self._prices.get(symbol_a)
        if prices_a:
            ts = prices_a[-1][0]

        snapshot = CrossAssetSnapshot(
            symbol_a=symbol_a,
            symbol_b=symbol_b,
            timestamp_ms=ts,
        )

        returns_a = self._log_returns(symbol_a)
        returns_b = self._log_returns(symbol_b)

        if returns_a is None or returns_b is None:
            return snapshot

        # Align by taking the shorter length
        n = min(len(returns_a), len(returns_b))
        if n < MIN_OBSERVATIONS:
            return snapshot

        ra = returns_a[-n:]
        rb = returns_b[-n:]

        snapshot.correlation = self._pearson(ra, rb)
        snapshot.relative_strength = self._relative_strength(symbol_a, symbol_b, n)
        snapshot.spread_z_score = self._spread_z_score(symbol_a, symbol_b)

        return snapshot

    def get_all_snapshots(self) -> list[CrossAssetSnapshot]:
        """Compute snapshots for all unique symbol pairs."""
        syms = sorted(self._prices.keys())
        snapshots = []
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                snap = self.get_snapshot(syms[i], syms[j])
                snapshots.append(snap)
        return snapshots

    def _log_returns(self, symbol: str) -> list[float] | None:
        """Compute log returns for a symbol's price history."""
        if symbol not in self._prices:
            return None
        prices = self._prices[symbol]
        if len(prices) < 2:
            return None

        returns = []
        prev_price = prices[0][1]
        for _, price in list(prices)[1:]:
            if prev_price > 0 and price > 0:
                returns.append(math.log(price / prev_price))
            prev_price = price
        return returns

    def _pearson(self, xs: list[float], ys: list[float]) -> float | None:
        """Pearson correlation between two return series."""
        n = len(xs)
        if n < MIN_OBSERVATIONS:
            return None

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / n
        var_x = sum((x - mean_x) ** 2 for x in xs) / n
        var_y = sum((y - mean_y) ** 2 for y in ys) / n

        if var_x < 1e-15 or var_y < 1e-15:
            return None

        return cov / math.sqrt(var_x * var_y)

    def _relative_strength(self, symbol_a: str, symbol_b: str, n: int) -> float | None:
        """Ratio of cumulative returns: sum(returns_a) / sum(returns_b)."""
        returns_a = self._log_returns(symbol_a)
        returns_b = self._log_returns(symbol_b)
        if returns_a is None or returns_b is None:
            return None

        ra = returns_a[-n:]
        rb = returns_b[-n:]

        cum_a = sum(ra)
        cum_b = sum(rb)

        if abs(cum_b) < 1e-15:
            return None

        return cum_a / cum_b

    def _spread_z_score(self, symbol_a: str, symbol_b: str) -> float | None:
        """Z-score of the log price ratio (symbol_a / symbol_b).

        Uses the full available history for the mean/std of the ratio,
        then computes z = (current_ratio - mean) / std.
        """
        prices_a = self._prices.get(symbol_a)
        prices_b = self._prices.get(symbol_b)
        if prices_a is None or prices_b is None:
            return None

        # Build aligned log-ratio series using timestamps
        # Simple approach: use the last min(len_a, len_b) observations
        n = min(len(prices_a), len(prices_b))
        if n < MIN_OBSERVATIONS:
            return None

        list_a = list(prices_a)[-n:]
        list_b = list(prices_b)[-n:]

        ratios = []
        for (_, pa), (_, pb) in zip(list_a, list_b, strict=True):
            if pa > 0 and pb > 0:
                ratios.append(math.log(pa / pb))

        if len(ratios) < MIN_OBSERVATIONS:
            return None

        mean_r = sum(ratios) / len(ratios)
        var_r = sum((r - mean_r) ** 2 for r in ratios) / len(ratios)
        if var_r < 1e-15:
            return None

        std_r = math.sqrt(var_r)
        current_ratio = ratios[-1]
        return (current_ratio - mean_r) / std_r
