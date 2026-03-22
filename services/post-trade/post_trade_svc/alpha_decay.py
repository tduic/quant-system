"""Alpha decay tracking: measures how signal IC decays over time horizons.

Records each signal emission with its predicted direction and the mid price
at signal time. As trades arrive, records the actual return at each
configured time horizon. Computes the Pearson IC (information coefficient)
between predicted direction and realised return at each horizon — both
overall and per-strategy.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Horizon label formatting
# ---------------------------------------------------------------------------


def _format_horizon(ms: int) -> str:
    """Convert milliseconds to a human-readable label."""
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h"


# ---------------------------------------------------------------------------
# Signal tracking record
# ---------------------------------------------------------------------------


@dataclass
class TrackedSignal:
    """A signal being tracked for alpha decay analysis."""

    signal_id: str
    timestamp_ms: int
    strategy_id: str
    symbol: str
    predicted_direction: float  # +strength for BUY, -strength for SELL
    mid_price: float
    horizon_returns: dict[int, float | None] = field(default_factory=dict)

    @property
    def fully_filled(self) -> bool:
        """True if all horizons have been evaluated."""
        return all(v is not None for v in self.horizon_returns.values())


# ---------------------------------------------------------------------------
# IC computation helper
# ---------------------------------------------------------------------------


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient. Returns None if undefined."""
    n = len(xs)
    if n < 5:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    var_y = sum((y - mean_y) ** 2 for y in ys) / n

    denom = math.sqrt(var_x * var_y)
    if denom < 1e-15:
        return None

    return cov / denom


# ---------------------------------------------------------------------------
# Main tracker
# ---------------------------------------------------------------------------

DEFAULT_HORIZONS_MS = [60_000, 300_000, 900_000, 1_800_000, 3_600_000]


class AlphaDecayTracker:
    """Tracks signal predictions and computes IC at configurable horizons.

    Parameters
    ----------
    horizons_ms
        List of time horizons in milliseconds at which to evaluate
        signal returns (default: 1m, 5m, 15m, 30m, 1h).
    max_signals
        Maximum number of signals to retain. Oldest signals are evicted
        when this limit is exceeded.
    """

    def __init__(
        self,
        horizons_ms: list[int] | None = None,
        max_signals: int = 1000,
    ) -> None:
        self._horizons_ms = sorted(horizons_ms or DEFAULT_HORIZONS_MS)
        self._max_signals = max_signals
        self._signals: deque[TrackedSignal] = deque(maxlen=max_signals)
        self._horizon_labels = {h: _format_horizon(h) for h in self._horizons_ms}

    # -------------------------------------------------------------------
    # Ingest
    # -------------------------------------------------------------------

    def record_signal(
        self,
        signal_id: str,
        timestamp_ms: int,
        strategy_id: str,
        symbol: str,
        side: str,
        strength: float,
        mid_price: float,
    ) -> None:
        """Record a new signal for tracking."""
        direction = strength if side.upper() == "BUY" else -strength
        sig = TrackedSignal(
            signal_id=signal_id,
            timestamp_ms=timestamp_ms,
            strategy_id=strategy_id,
            symbol=symbol,
            predicted_direction=direction,
            mid_price=mid_price,
            horizon_returns={h: None for h in self._horizons_ms},
        )
        self._signals.append(sig)

    def on_trade(self, symbol: str, timestamp_ms: int, price: float) -> None:
        """Process a trade tick to evaluate pending horizon returns."""
        for sig in self._signals:
            if sig.fully_filled:
                continue
            if sig.symbol != symbol:
                continue
            if sig.mid_price == 0:
                continue

            for h_ms in self._horizons_ms:
                if sig.horizon_returns[h_ms] is not None:
                    continue  # already filled
                if timestamp_ms >= sig.timestamp_ms + h_ms:
                    actual_return = (price - sig.mid_price) / sig.mid_price
                    sig.horizon_returns[h_ms] = actual_return

    # -------------------------------------------------------------------
    # IC computation
    # -------------------------------------------------------------------

    def _compute_ic_for_signals(
        self,
        signals: list[TrackedSignal],
        horizon_ms: int,
    ) -> tuple[float | None, int]:
        """Compute IC for a set of signals at a given horizon.

        Returns (ic_value, filled_count).
        """
        predictions = []
        returns = []
        for sig in signals:
            ret = sig.horizon_returns.get(horizon_ms)
            if ret is not None:
                predictions.append(sig.predicted_direction)
                returns.append(ret)

        ic = _pearson_correlation(predictions, returns)
        return ic, len(predictions)

    # -------------------------------------------------------------------
    # Dashboard data
    # -------------------------------------------------------------------

    def get_alpha_decay_data(self, symbol: str | None = None) -> dict:
        """Return alpha decay data for the dashboard endpoint."""
        all_signals = list(self._signals)
        if symbol:
            all_signals = [s for s in all_signals if s.symbol == symbol.upper()]

        # Overall IC at each horizon
        horizons = []
        for h_ms in self._horizons_ms:
            ic, filled = self._compute_ic_for_signals(all_signals, h_ms)
            horizons.append(
                {
                    "horizon_ms": h_ms,
                    "horizon_label": self._horizon_labels[h_ms],
                    "ic": round(ic, 4) if ic is not None else None,
                    "filled_count": filled,
                    "total_signals": len(all_signals),
                }
            )

        # Per-strategy breakdown
        strategy_signals: dict[str, list[TrackedSignal]] = {}
        for sig in all_signals:
            strategy_signals.setdefault(sig.strategy_id, []).append(sig)

        strategies = {}
        for strat_id, strat_sigs in strategy_signals.items():
            strat_horizons = []
            for h_ms in self._horizons_ms:
                ic, filled = self._compute_ic_for_signals(strat_sigs, h_ms)
                strat_horizons.append(
                    {
                        "horizon_ms": h_ms,
                        "horizon_label": self._horizon_labels[h_ms],
                        "ic": round(ic, 4) if ic is not None else None,
                        "filled_count": filled,
                    }
                )
            strategies[strat_id] = {
                "signal_count": len(strat_sigs),
                "horizons": strat_horizons,
            }

        return {
            "horizons": horizons,
            "total_signals": len(all_signals),
            "strategies": strategies,
        }
