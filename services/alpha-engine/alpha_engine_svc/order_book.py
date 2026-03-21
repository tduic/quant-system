"""In-memory order book maintained from depth updates.

This is the Python implementation. Will be swapped for a C++ pybind11
module in Phase 6 without changing the interface.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from quant_core.models import DepthUpdate

logger = logging.getLogger(__name__)


class OrderBook:
    """L2 order book maintained from incremental depth updates.

    Interface contract (preserved when migrating to C++):
        - apply_delta(update: DepthUpdate) -> None
        - best_bid() -> tuple[float, float] | None
        - best_ask() -> tuple[float, float] | None
        - mid_price() -> float | None
        - spread() -> float | None
        - imbalance(levels: int = 5) -> float
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._bids: dict[float, float] = {}  # price -> quantity
        self._asks: dict[float, float] = {}

    def apply_delta(self, update: DepthUpdate) -> None:
        """Apply an incremental depth update to the book."""
        for price, qty in update.bids:
            if qty == 0.0:
                self._bids.pop(price, None)
            else:
                self._bids[price] = qty

        for price, qty in update.asks:
            if qty == 0.0:
                self._asks.pop(price, None)
            else:
                self._asks[price] = qty

    def best_bid(self) -> tuple[float, float] | None:
        """Highest bid (price, quantity)."""
        if not self._bids:
            return None
        price = max(self._bids)
        return (price, self._bids[price])

    def best_ask(self) -> tuple[float, float] | None:
        """Lowest ask (price, quantity)."""
        if not self._asks:
            return None
        price = min(self._asks)
        return (price, self._asks[price])

    def mid_price(self) -> float | None:
        """Midpoint between best bid and best ask."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid[0] + ask[0]) / 2.0

    def spread(self) -> float | None:
        """Spread between best ask and best bid."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return ask[0] - bid[0]

    def imbalance(self, levels: int = 5) -> float:
        """Order book imbalance ratio across top N levels.

        Returns a value between -1.0 (all ask pressure) and 1.0 (all bid pressure).
        0.0 means balanced.
        """
        bid_prices = sorted(self._bids.keys(), reverse=True)[:levels]
        ask_prices = sorted(self._asks.keys())[:levels]

        bid_volume = sum(self._bids[p] for p in bid_prices)
        ask_volume = sum(self._asks[p] for p in ask_prices)

        total = bid_volume + ask_volume
        if total == 0.0:
            return 0.0

        return (bid_volume - ask_volume) / total

    def top_bids(self, levels: int = 10) -> list[tuple[float, float]]:
        """Top N bid levels sorted by price descending."""
        prices = sorted(self._bids.keys(), reverse=True)[:levels]
        return [(p, self._bids[p]) for p in prices]

    def top_asks(self, levels: int = 10) -> list[tuple[float, float]]:
        """Top N ask levels sorted by price ascending."""
        prices = sorted(self._asks.keys())[:levels]
        return [(p, self._asks[p]) for p in prices]
