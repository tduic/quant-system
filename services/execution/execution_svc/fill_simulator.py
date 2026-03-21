"""Paper trading fill simulator.

Simulates order fills using current market data. Models slippage
based on order size relative to available liquidity.

Phase 3 will add Brownian bridge slippage for more realistic simulation.
Phase 6 will swap this for a C++ matching engine.
"""

from __future__ import annotations

import logging
import uuid

from quant_core.models import Fill, Order, now_ms

logger = logging.getLogger(__name__)

# Default fee rate (Coinbase taker fee for < $10k volume)
DEFAULT_FEE_RATE = 0.006  # 0.6%


class FillSimulator:
    """Simulates order fills for paper trading.

    Interface contract (preserved when migrating to C++):
        - simulate_fill(order, mid_price, spread, book_depth) -> Fill
    """

    def __init__(self, fee_rate: float = DEFAULT_FEE_RATE):
        self._fee_rate = fee_rate

    def simulate_fill(
        self,
        order: Order,
        mid_price: float,
        spread: float,
        book_depth: list[tuple[float, float]] | None = None,
    ) -> Fill:
        """Simulate a market order fill.

        For now, fills at mid_price + half spread (buy) or mid_price - half spread (sell).
        Phase 3 adds walk-the-book logic using book_depth and Brownian bridge.
        """
        half_spread = spread / 2.0

        fill_price = mid_price + half_spread if order.side == "BUY" else mid_price - half_spread

        # Slippage in basis points vs mid price
        slippage_bps = abs(fill_price - mid_price) / mid_price * 10_000

        fee = order.quantity * fill_price * self._fee_rate

        return Fill(
            fill_id=str(uuid.uuid4()),
            timestamp=now_ms(),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            fee=fee,
            slippage_bps=slippage_bps,
            backtest_id=order.backtest_id,
            strategy_id=order.strategy_id,
        )
