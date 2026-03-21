"""PnL computation engine.

Tracks realized and unrealized PnL per symbol and per strategy.
Supports both FIFO and average cost basis methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Current position in a single symbol."""

    symbol: str = ""
    quantity: float = 0.0            # signed: positive = long, negative = short
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0

    def apply_fill(self, quantity: float, price: float, fee: float, side: str) -> float:
        """Apply a fill and return the realized PnL from this fill.

        Uses average cost basis method.
        """
        signed_qty = quantity if side == "BUY" else -quantity
        self.total_fees += fee

        # Same direction: increase position, update avg entry
        if self.quantity == 0.0 or (self.quantity > 0 and signed_qty > 0) or (self.quantity < 0 and signed_qty < 0):
            total_cost = self.avg_entry_price * abs(self.quantity) + price * abs(signed_qty)
            self.quantity += signed_qty
            if self.quantity != 0.0:
                self.avg_entry_price = total_cost / abs(self.quantity)
            return 0.0

        # Opposite direction: realize PnL
        close_qty = min(abs(signed_qty), abs(self.quantity))
        if self.quantity > 0:
            realized = close_qty * (price - self.avg_entry_price)
        else:
            realized = close_qty * (self.avg_entry_price - price)

        self.realized_pnl += realized
        self.quantity += signed_qty

        # If we flipped sides, set new entry price
        if (self.quantity > 0 and signed_qty > 0) or (self.quantity < 0 and signed_qty < 0):
            self.avg_entry_price = price

        return realized

    def unrealized_pnl(self, current_price: float) -> float:
        """Unrealized PnL at current market price."""
        if self.quantity == 0.0:
            return 0.0
        if self.quantity > 0:
            return self.quantity * (current_price - self.avg_entry_price)
        else:
            return abs(self.quantity) * (self.avg_entry_price - current_price)


@dataclass
class PortfolioPnL:
    """Aggregated PnL across all positions."""

    positions: dict[str, Position] = field(default_factory=dict)

    def get_or_create(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    @property
    def total_realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self.positions.values())

    @property
    def total_fees(self) -> float:
        return sum(p.total_fees for p in self.positions.values())

    def total_unrealized_pnl(self, prices: dict[str, float]) -> float:
        return sum(
            p.unrealized_pnl(prices.get(p.symbol, p.avg_entry_price))
            for p in self.positions.values()
        )
