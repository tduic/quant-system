"""Simple mean-reversion strategy.

Trades when price deviates from a rolling VWAP by more than a
configurable number of standard deviations. Extremely simple —
intended as the V1 starter strategy to validate the pipeline.

Signal logic:
    - If price < vwap - threshold_std * volatility → BUY (price is cheap)
    - If price > vwap + threshold_std * volatility → SELL (price is expensive)
    - Otherwise → no signal

The strategy needs a minimum number of trades (warmup period) before
generating any signals to avoid trading on insufficient data.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from alpha_engine_svc.feature_engine import FeatureEngine
from alpha_engine_svc.strategy import BaseStrategy
from quant_core.models import DepthUpdate, Signal, Trade, now_ms

logger = logging.getLogger(__name__)

DEFAULT_PARAMS = {
    "window_size": 200,  # number of trades in rolling window
    "threshold_std": 2.5,  # z-score threshold to trigger signal
    "warmup_trades": 100,  # minimum trades before generating signals
    "cooldown_trades": 30,  # minimum trades between signals
    # Volatility-scaled position sizing:
    #   quantity = target_risk_usd / (price * volatility * sqrt(holding_period_trades))
    # This normalizes expected dollar P&L variance across assets.
    # During low-vol periods, sizes up (more notional, same risk).
    # During high-vol periods, sizes down (less notional, same risk).
    "target_risk_usd": 15.0,  # target dollar risk per trade
    "max_notional_usd": 500.0,  # hard cap on trade notional
    "min_notional_usd": 10.0,  # floor to avoid dust orders
    "holding_period_trades": 30,  # expected trades until exit (for vol scaling)
}


class MeanReversionStrategy(BaseStrategy):
    """Fade deviations from VWAP."""

    def __init__(
        self,
        strategy_id: str = "mean_reversion_v1",
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
        self._last_signal_side: str | None = None

        # Book state
        self._mid_price: float | None = None
        self._spread: float | None = None

    @property
    def is_warmed_up(self) -> bool:
        return self._trade_count >= self.params["warmup_trades"]

    @property
    def cooldown_elapsed(self) -> bool:
        return self._trades_since_last_signal >= self.params["cooldown_trades"]

    def on_trade(self, trade: Trade) -> Signal | None:
        self._trade_count += 1
        self._trades_since_last_signal += 1

        self._feature_engine.on_trade(
            price=trade.price,
            quantity=trade.quantity,
            is_buyer_maker=trade.is_buyer_maker,
            timestamp_ms=trade.timestamp_exchange,
        )

        if not self.is_warmed_up:
            return None

        if not self.cooldown_elapsed:
            return None

        features = self._feature_engine.compute()

        if features.vwap == 0.0 or features.volatility == 0.0:
            return None

        # Z-score: how many vols away from VWAP
        # Volatility is in return space, so scale by VWAP to get absolute price vol
        abs_volatility = features.volatility * features.vwap
        z_score = (trade.price - features.vwap) / abs_volatility if abs_volatility > 0 else 0.0
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

        # Don't send duplicate signals in the same direction
        if side == self._last_signal_side:
            return None

        self._last_signal_side = side
        self._trades_since_last_signal = 0

        # --- Volatility-scaled position sizing ---
        # quantity = target_risk / (price * vol * sqrt(holding_period))
        # This gives each trade roughly equal expected dollar P&L variance,
        # regardless of whether we're trading $75K BTC or $88 SOL.
        price = self._mid_price or trade.price
        holding_vol = features.volatility * math.sqrt(self.params["holding_period_trades"])

        if holding_vol > 0 and price > 0:
            quantity = self.params["target_risk_usd"] / (price * holding_vol)
            # Clamp by notional bounds
            notional = quantity * price
            if notional > self.params["max_notional_usd"]:
                quantity = self.params["max_notional_usd"] / price
            elif notional < self.params["min_notional_usd"]:
                quantity = self.params["min_notional_usd"] / price
        else:
            # Fallback: $100 notional if vol not available
            quantity = 100.0 / price if price > 0 else 0.001

        # Urgency determines order type (LIMIT vs MARKET):
        #   z near threshold (2.5-3.5) → low urgency → LIMIT (maker fee)
        #   z far from threshold (>3.5) → high urgency → MARKET (taker fee)
        # Most signals should be limit orders to save on fees.
        z_excess = abs(z_score) - threshold
        urgency = min(z_excess / threshold, 1.0)  # 0.0 at threshold, 1.0 at 2x threshold

        return Signal(
            timestamp=now_ms(),
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            side=side,
            strength=strength,
            target_quantity=round(quantity, 8),
            urgency=urgency,
            mid_price_at_signal=price,
            spread_at_signal=self._spread or 0.0,
            metadata={
                "z_score": round(z_score, 4),
                "vwap": round(features.vwap, 2),
                "volatility": round(features.volatility, 8),
                "trade_rate": round(features.trade_rate, 2),
                "notional_usd": round(quantity * price, 2),
            },
        )

    def on_book_update(self, update: DepthUpdate) -> Signal | None:
        """Update book state for mid_price/spread tracking. Never generates signals."""
        # We compute from the update's bids/asks directly
        if update.bids and update.asks:
            best_bid = max(b[0] for b in update.bids) if update.bids else None
            best_ask = min(a[0] for a in update.asks) if update.asks else None
            if best_bid and best_ask:
                self._mid_price = (best_bid + best_ask) / 2.0
                self._spread = best_ask - best_bid

        self._feature_engine.on_book_snapshot(
            mid_price=self._mid_price,
            spread=self._spread,
            imbalance=0.0,  # computed by order book, not here
        )
        return None
