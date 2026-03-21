"""Transaction Cost Analysis (TCA).

Decomposes execution costs into components: spread, slippage, market impact,
and fees. Used to evaluate execution quality.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TCAResult:
    """Breakdown of execution costs for a single fill."""

    fill_id: str = ""
    symbol: str = ""
    side: str = ""

    # Prices
    decision_price: float = 0.0  # mid price when signal was generated
    arrival_price: float = 0.0  # mid price when order reached execution
    fill_price: float = 0.0  # actual execution price

    # Cost decomposition (all in basis points)
    spread_cost_bps: float = 0.0  # half-spread cost
    slippage_bps: float = 0.0  # arrival price vs fill price
    market_impact_bps: float = 0.0  # decision price vs arrival price (alpha decay)
    fee_bps: float = 0.0  # exchange fee as bps of notional
    total_cost_bps: float = 0.0  # all-in cost


def analyze_fill(
    fill_id: str,
    symbol: str,
    side: str,
    decision_price: float,
    arrival_price: float,
    fill_price: float,
    fee: float,
    quantity: float,
) -> TCAResult:
    """Compute TCA breakdown for a single fill."""

    notional = quantity * fill_price
    fee_bps = (fee / notional * 10_000) if notional > 0 else 0.0

    if side == "BUY":
        market_impact_bps = (arrival_price - decision_price) / decision_price * 10_000
        slippage_bps = (fill_price - arrival_price) / arrival_price * 10_000
    else:
        market_impact_bps = (decision_price - arrival_price) / decision_price * 10_000
        slippage_bps = (arrival_price - fill_price) / arrival_price * 10_000

    spread_cost_bps = abs(fill_price - arrival_price) / arrival_price * 10_000 if arrival_price > 0 else 0.0

    total_cost_bps = abs(market_impact_bps) + abs(slippage_bps) + fee_bps

    return TCAResult(
        fill_id=fill_id,
        symbol=symbol,
        side=side,
        decision_price=decision_price,
        arrival_price=arrival_price,
        fill_price=fill_price,
        spread_cost_bps=spread_cost_bps,
        slippage_bps=slippage_bps,
        market_impact_bps=market_impact_bps,
        fee_bps=fee_bps,
        total_cost_bps=total_cost_bps,
    )
