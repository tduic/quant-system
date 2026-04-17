"""Paper trading fill simulator.

Simulates order fills using current market data. Two models available:

1. Simple: fills at mid ± half spread (Phase 2)
2. Brownian bridge: models price movement between decision and fill,
   plus walk-the-book for market impact (Phase 3)

Phase 6 will swap this for a C++ matching engine.
"""

from __future__ import annotations

import logging
import math
import random
import uuid

from quant_core.models import Fill, Order, now_ms

logger = logging.getLogger(__name__)

# Coinbase Advanced Trade fee schedule (2026)
# Tiers based on trailing 30-day USD volume, updated hourly.
# Each entry: (volume_threshold, maker_rate, taker_rate)
COINBASE_FEE_TIERS: list[tuple[float, float, float]] = [
    (1_000, 0.0060, 0.0120),        # $0 - $1K
    (10_000, 0.0035, 0.0075),       # $1K - $10K
    (50_000, 0.0025, 0.0040),       # $10K - $50K
    (500_000, 0.0015, 0.0025),      # $50K - $500K
    (1_000_000, 0.0010, 0.0020),    # $500K - $1M
    (15_000_000, 0.0007, 0.0016),   # $1M - $15M
    (50_000_000, 0.0005, 0.0014),   # $15M - $50M
    (100_000_000, 0.0002, 0.0010),  # $50M - $100M
    (250_000_000, 0.0000, 0.0008),  # $100M - $250M
    (float("inf"), 0.0000, 0.0005), # $250M+
]


def coinbase_fee_rate(volume_30d: float, is_maker: bool = True) -> float:
    """Look up Coinbase fee rate for a given 30-day volume."""
    for threshold, maker, taker in COINBASE_FEE_TIERS:
        if volume_30d < threshold:
            return maker if is_maker else taker
    return COINBASE_FEE_TIERS[-1][1] if is_maker else COINBASE_FEE_TIERS[-1][2]


# Default: assume low-volume taker (worst case, most realistic for small accounts)
DEFAULT_FEE_RATE = 0.0075  # 0.75% taker at $1K-$10K tier

# Default latency for order to reach exchange (ms)
DEFAULT_LATENCY_MS = 50


def brownian_bridge_sample(
    start_price: float,
    end_price: float,
    volatility: float,
    dt_seconds: float,
) -> float:
    """Sample a price from a Brownian bridge between two known endpoints.

    Models the price path between the moment you decide to trade (start_price)
    and the moment your order would arrive at the exchange (end_price is the
    current observed price). The fill happens somewhere along this path.

    The bridge is conditioned on both endpoints, with variance:
        Var = sigma^2 * t * (total_time-t) / total_time

    where t is the fill time and total_time is total interval.
    For simplicity, we sample at t = total_time/2 (midpoint of the journey).
    """
    if dt_seconds <= 0 or volatility <= 0:
        return (start_price + end_price) / 2.0

    # Midpoint of bridge
    t = dt_seconds / 2.0
    total_time = dt_seconds

    # Bridge mean at midpoint
    bridge_mean = start_price + (end_price - start_price) * (t / total_time)

    # Bridge variance at midpoint: sigma^2 * t * (total_time-t) / total_time
    bridge_var = (volatility**2) * t * (total_time - t) / total_time
    bridge_std = bridge_var**0.5

    # Sample from normal distribution
    z = random.gauss(0, 1)
    return bridge_mean + z * bridge_std


def walk_the_book(
    quantity: float,
    book_depth: list[tuple[float, float]],
) -> float:
    """Walk the order book to compute average fill price.

    book_depth is sorted levels: [(price, size), ...] where:
    - For buys: ascending ask prices
    - For sells: descending bid prices

    Returns the volume-weighted average fill price.
    """
    if not book_depth:
        return 0.0

    remaining = quantity
    total_cost = 0.0

    for price, size in book_depth:
        fill_at_level = min(remaining, size)
        total_cost += fill_at_level * price
        remaining -= fill_at_level
        if remaining <= 0:
            break

    filled_qty = quantity - remaining
    if filled_qty <= 0:
        return book_depth[0][0]  # best price if can't fill

    return total_cost / filled_qty


class FillSimulator:
    """Simulates order fills for paper trading.

    Interface contract (preserved when migrating to C++):
        - simulate_fill(order, mid_price, spread, book_depth) -> Fill
    """

    def __init__(
        self,
        fee_rate: float | None = None,
        use_brownian_bridge: bool = False,
        latency_ms: float = DEFAULT_LATENCY_MS,
        use_tiered_fees: bool = True,
    ):
        self._fixed_fee_rate = fee_rate
        self._use_tiered_fees = use_tiered_fees and fee_rate is None
        self._use_brownian_bridge = use_brownian_bridge
        self._latency_ms = latency_ms
        self._last_volatility: float = 0.0
        self._rolling_volume_30d: float = 0.0  # tracked externally or estimated

    def set_volatility(self, volatility: float) -> None:
        """Update the current volatility estimate (annualized)."""
        self._last_volatility = volatility

    def set_rolling_volume(self, volume_30d: float) -> None:
        """Update trailing 30-day volume for tiered fee calculation."""
        self._rolling_volume_30d = volume_30d

    def fee_rate_for_order(self, order: Order) -> tuple[float, bool]:
        """Return (fee_rate, is_maker) for an order based on its type and volume tier.

        LIMIT orders are maker (add liquidity), MARKET orders are taker (remove liquidity).
        """
        is_maker = order.order_type == "LIMIT"
        if self._fixed_fee_rate is not None:
            return self._fixed_fee_rate, is_maker
        if self._use_tiered_fees:
            return coinbase_fee_rate(self._rolling_volume_30d, is_maker), is_maker
        return DEFAULT_FEE_RATE, is_maker

    def simulate_fill(
        self,
        order: Order,
        mid_price: float,
        spread: float,
        book_depth: list[tuple[float, float]] | None = None,
    ) -> Fill:
        """Simulate an order fill with maker/taker fee distinction.

        LIMIT orders pay maker fees (lower), MARKET orders pay taker fees (higher).
        For LIMIT orders, fills at the limit price (no spread crossing).
        For MARKET orders, fills at mid ± half spread (or via book/bridge model).
        """
        is_maker = order.order_type == "LIMIT"

        if is_maker and order.limit_price is not None:
            # Maker: fill at the limit price (assumes it gets filled)
            fill_price = order.limit_price
        elif self._use_brownian_bridge and self._last_volatility > 0:
            fill_price = self._brownian_bridge_fill(order, mid_price, spread, book_depth)
        elif book_depth:
            fill_price = walk_the_book(order.quantity, book_depth)
        else:
            fill_price = self._simple_fill(order, mid_price, spread)

        slippage_bps = abs(fill_price - mid_price) / mid_price * 10_000 if mid_price > 0 else 0.0
        notional = order.quantity * fill_price
        fee_rate, _ = self.fee_rate_for_order(order)
        fee = notional * fee_rate

        # Update rolling volume estimate for tiered fee calculation
        self._rolling_volume_30d += notional

        return Fill(
            fill_id=str(uuid.uuid4()),
            timestamp=now_ms(),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            fee=fee,
            fee_rate=fee_rate,
            is_maker=is_maker,
            slippage_bps=slippage_bps,
            backtest_id=order.backtest_id,
            strategy_id=order.strategy_id,
        )

    def _simple_fill(self, order: Order, mid_price: float, spread: float) -> float:
        """Simple fill at mid ± half spread."""
        half_spread = spread / 2.0
        return mid_price + half_spread if order.side == "BUY" else mid_price - half_spread

    def _brownian_bridge_fill(
        self,
        order: Order,
        mid_price: float,
        spread: float,
        book_depth: list[tuple[float, float]] | None,
    ) -> float:
        """Brownian bridge fill: model price movement during latency."""
        dt_seconds = self._latency_ms / 1000.0

        # Convert annualized vol to per-second vol
        # Crypto: 365 * 24 * 3600 seconds per year
        seconds_per_year = 365.0 * 24.0 * 3600.0
        vol_per_second = self._last_volatility / math.sqrt(seconds_per_year)

        # The "decision price" is mid_price. The "arrival price" includes
        # the bridge-sampled price movement during latency.
        half_spread = spread / 2.0
        arrival_side = mid_price + half_spread if order.side == "BUY" else mid_price - half_spread

        # Sample bridge between decision and arrival
        bridge_price = brownian_bridge_sample(
            start_price=mid_price,
            end_price=arrival_side,
            volatility=vol_per_second * mid_price,  # absolute vol
            dt_seconds=dt_seconds,
        )

        # Walk the book if depth available, otherwise use bridge price
        if book_depth:
            book_fill = walk_the_book(order.quantity, book_depth)
            # Blend: bridge captures timing, book captures impact
            fill_price = (bridge_price + book_fill) / 2.0
        else:
            fill_price = bridge_price

        return fill_price
