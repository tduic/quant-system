"""Simple momentum strategy.

Trades in the direction of price breakouts from a rolling VWAP.
Mirror image of MeanReversionStrategy — when mean reversion would
fade a move, momentum rides it.

Signal logic:
    - If price > vwap + threshold_std * volatility → BUY  (ride the rally)
    - If price < vwap - threshold_std * volatility → SELL (ride the breakdown)
    - Otherwise → no signal

Uses the same vol-scaled position sizing and urgency→order-type mapping
as mean reversion, for apples-to-apples comparison.
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
    "window_size": 200,
    "threshold_std": 2.5,
    "warmup_trades": 100,
    "cooldown_trades": 30,
    "target_risk_usd": 15.0,
    "max_notional_usd": 500.0,
    "min_notional_usd": 10.0,
    "holding_period_trades": 30,
}


class MomentumStrategy(BaseStrategy):
    """Ride breakouts from VWAP."""

    def __init__(
        self,
        strategy_id: str = "momentum_v1",
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

        if not self.is_warmed_up or not self.cooldown_elapsed:
            return None

        features = self._feature_engine.compute()

        if features.vwap == 0.0 or features.volatility == 0.0:
            return None

        abs_volatility = features.volatility * features.vwap
        z_score = (trade.price - features.vwap) / abs_volatility if abs_volatility > 0 else 0.0
        threshold = self.params["threshold_std"]

        # Momentum: ride the direction of the breakout (opposite of mean reversion)
        side = None
        strength = 0.0

        if z_score > threshold:
            side = "BUY"
            strength = min(abs(z_score) / (threshold * 2), 1.0)
        elif z_score < -threshold:
            side = "SELL"
            strength = min(abs(z_score) / (threshold * 2), 1.0)

        if side is None:
            return None

        if side == self._last_signal_side:
            return None

        self._last_signal_side = side
        self._trades_since_last_signal = 0

        # Volatility-scaled position sizing
        price = self._mid_price or trade.price
        holding_vol = features.volatility * math.sqrt(self.params["holding_period_trades"])

        if holding_vol > 0 and price > 0:
            quantity = self.params["target_risk_usd"] / (price * holding_vol)
            notional = quantity * price
            if notional > self.params["max_notional_usd"]:
                quantity = self.params["max_notional_usd"] / price
            elif notional < self.params["min_notional_usd"]:
                quantity = self.params["min_notional_usd"] / price
        else:
            if price > 0:
                quantity = self.params["min_notional_usd"] / price
            else:
                logger.warning("Price is 0 for %s, skipping signal", self.symbol)
                return None

        z_excess = abs(z_score) - threshold
        urgency = min(z_excess / threshold, 1.0)

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
        if update.bids and update.asks:
            best_bid = max(b[0] for b in update.bids) if update.bids else None
            best_ask = min(a[0] for a in update.asks) if update.asks else None
            if best_bid and best_ask:
                self._mid_price = (best_bid + best_ask) / 2.0
                self._spread = best_ask - best_bid

        self._feature_engine.on_book_snapshot(
            mid_price=self._mid_price,
            spread=self._spread,
            imbalance=0.0,
        )
        return None
