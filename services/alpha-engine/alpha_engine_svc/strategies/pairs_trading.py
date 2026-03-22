"""Pairs trading strategy.

Monitors the log price ratio between two correlated assets and trades
mean-reversion of the spread. Requires a CrossAssetTracker to provide
correlation and z-score data.

Signal logic:
    - If spread z-score < -entry_threshold → BUY leg_a, SELL leg_b
    - If spread z-score > +entry_threshold → SELL leg_a, BUY leg_b
    - Requires minimum correlation before trading
    - Cooldown between signals to prevent overtrading
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from alpha_engine_svc.strategy import BaseStrategy
from quant_core.models import DepthUpdate, Signal, Trade, now_ms

if TYPE_CHECKING:
    from alpha_engine_svc.cross_asset import CrossAssetTracker

logger = logging.getLogger(__name__)

DEFAULT_PARAMS = {
    "entry_threshold": 2.0,  # z-score threshold to open a position
    "min_correlation": 0.5,  # minimum absolute correlation to trade
    "base_quantity": 0.001,  # order size per leg
    "cooldown_trades": 20,  # trades between signals
    "warmup_trades": 30,  # min trades before generating signals
}


class PairsTradingStrategy(BaseStrategy):
    """Mean-reversion on the spread between two correlated assets.

    This strategy is registered for symbol_a but watches the cross-asset
    tracker for the pair (symbol_a, symbol_b). It emits signals for
    symbol_a only — the counterpart leg for symbol_b is emitted separately
    by calling `get_counterpart_signal()`.
    """

    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        symbol_b: str,
        cross_asset_tracker: CrossAssetTracker,
        params: dict[str, Any] | None = None,
    ):
        merged = {**DEFAULT_PARAMS, **(params or {})}
        super().__init__(strategy_id=strategy_id, symbol=symbol, params=merged)
        self._symbol_b = symbol_b
        self._tracker = cross_asset_tracker
        self._trade_count = 0
        self._trades_since_last_signal = 0
        self._last_signal_side: str | None = None
        self._pending_counterpart: Signal | None = None

    @property
    def symbol_b(self) -> str:
        return self._symbol_b

    @property
    def is_warmed_up(self) -> bool:
        return self._trade_count >= self.params["warmup_trades"]

    @property
    def cooldown_elapsed(self) -> bool:
        return self._trades_since_last_signal >= self.params["cooldown_trades"]

    def on_trade(self, trade: Trade) -> Signal | None:
        """Process a trade tick for symbol_a. Returns signal for symbol_a if triggered."""
        self._trade_count += 1
        self._trades_since_last_signal += 1

        # Feed price to cross-asset tracker
        self._tracker.on_price(trade.symbol.upper(), trade.timestamp_exchange, trade.price)

        if not self.is_warmed_up or not self.cooldown_elapsed:
            return None

        snap = self._tracker.get_snapshot(self.symbol, self._symbol_b)

        if snap.correlation is None or snap.spread_z_score is None:
            return None

        # Only trade if sufficiently correlated
        if abs(snap.correlation) < self.params["min_correlation"]:
            return None

        z = snap.spread_z_score
        threshold = self.params["entry_threshold"]
        side_a = None

        if z < -threshold:
            # Spread is too low: A is cheap relative to B → BUY A, SELL B
            side_a = "BUY"
        elif z > threshold:
            # Spread is too high: A is expensive relative to B → SELL A, BUY B
            side_a = "SELL"

        if side_a is None:
            return None

        # Suppress duplicate signals in the same direction
        if side_a == self._last_signal_side:
            return None

        self._last_signal_side = side_a
        self._trades_since_last_signal = 0

        strength = min(abs(z) / (threshold * 2), 1.0)

        signal_a = Signal(
            timestamp=now_ms(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            side=side_a,
            strength=strength,
            target_quantity=self.params["base_quantity"],
            urgency=strength,
            mid_price_at_signal=trade.price,
            spread_at_signal=0.0,
            metadata={
                "pair": f"{self.symbol}/{self._symbol_b}",
                "z_score": round(z, 4),
                "correlation": round(snap.correlation, 4),
                "relative_strength": round(snap.relative_strength, 4) if snap.relative_strength else None,
                "leg": "A",
            },
        )

        # Prepare counterpart signal for leg B
        side_b = "SELL" if side_a == "BUY" else "BUY"
        self._pending_counterpart = Signal(
            timestamp=now_ms(),
            strategy_id=self.strategy_id,
            symbol=self._symbol_b,
            side=side_b,
            strength=strength,
            target_quantity=self.params["base_quantity"],
            urgency=strength,
            mid_price_at_signal=0.0,  # will be filled by caller with latest price
            spread_at_signal=0.0,
            metadata={
                "pair": f"{self.symbol}/{self._symbol_b}",
                "z_score": round(z, 4),
                "correlation": round(snap.correlation, 4),
                "relative_strength": round(snap.relative_strength, 4) if snap.relative_strength else None,
                "leg": "B",
            },
        )

        return signal_a

    def get_counterpart_signal(self) -> Signal | None:
        """Return and clear the pending counterpart signal for symbol_b."""
        sig = self._pending_counterpart
        self._pending_counterpart = None
        return sig

    def on_book_update(self, update: DepthUpdate) -> Signal | None:
        """Book updates don't trigger pairs signals."""
        return None
