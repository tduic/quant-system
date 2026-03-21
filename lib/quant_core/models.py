"""Shared data models used across all services.

These dataclasses define the canonical event formats that flow through Kafka.
All timestamps are in milliseconds since epoch (UTC).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import json


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Market Data Events
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """A single trade tick from an exchange."""

    type: str = "trade"
    exchange: str = "binance"
    symbol: str = ""
    trade_id: int = 0
    price: float = 0.0
    quantity: float = 0.0
    timestamp_exchange: int = 0       # ms since epoch
    timestamp_ingested: int = 0       # ms since epoch
    is_buyer_maker: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> Trade:
        data = json.loads(raw)
        return cls(**data)

    @classmethod
    def from_binance(cls, msg: dict, ingested_at: int) -> Trade:
        """Parse a Binance WebSocket trade message."""
        return cls(
            exchange="binance",
            symbol=msg["s"].upper(),
            trade_id=msg["t"],
            price=float(msg["p"]),
            quantity=float(msg["q"]),
            timestamp_exchange=msg["T"],
            timestamp_ingested=ingested_at,
            is_buyer_maker=msg["m"],
        )


@dataclass
class DepthUpdate:
    """An order book depth update from an exchange."""

    type: str = "depth_update"
    exchange: str = "binance"
    symbol: str = ""
    first_update_id: int = 0
    final_update_id: int = 0
    bids: list[list[float]] = field(default_factory=list)  # [[price, qty], ...]
    asks: list[list[float]] = field(default_factory=list)
    timestamp_exchange: int = 0
    timestamp_ingested: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> DepthUpdate:
        data = json.loads(raw)
        return cls(**data)

    @classmethod
    def from_binance(cls, msg: dict, ingested_at: int) -> DepthUpdate:
        """Parse a Binance WebSocket depth update message."""
        return cls(
            exchange="binance",
            symbol=msg.get("s", "").upper(),
            first_update_id=msg.get("U", 0),
            final_update_id=msg.get("u", 0),
            bids=[[float(p), float(q)] for p, q in msg.get("b", [])],
            asks=[[float(p), float(q)] for p, q in msg.get("a", [])],
            timestamp_exchange=msg.get("E", 0),
            timestamp_ingested=ingested_at,
        )


# ---------------------------------------------------------------------------
# Signal Events
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A trading signal emitted by the Alpha Engine."""

    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = 0
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""          # Side enum value
    strength: float = 0.0   # -1.0 to 1.0
    target_quantity: float = 0.0
    urgency: float = 0.5    # 0.0 to 1.0
    metadata: dict = field(default_factory=dict)
    mid_price_at_signal: float = 0.0
    spread_at_signal: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> Signal:
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
# Order / Fill Events
# ---------------------------------------------------------------------------

@dataclass
class Order:
    """An order submitted to the execution service."""

    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = 0
    symbol: str = ""
    side: str = ""
    order_type: str = "MARKET"
    quantity: float = 0.0
    limit_price: float | None = None
    status: str = "SUBMITTED"
    signal_id: str = ""
    strategy_id: str = ""
    backtest_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> Order:
        return cls(**json.loads(raw))


@dataclass
class Fill:
    """A fill event from the execution service."""

    fill_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: int = 0
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    fee: float = 0.0
    slippage_bps: float = 0.0
    backtest_id: str | None = None
    strategy_id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> Fill:
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
# Risk Events
# ---------------------------------------------------------------------------

@dataclass
class RiskDecision:
    """A risk check decision from the Risk Gateway."""

    signal_id: str = ""
    decision: str = ""          # "APPROVED" or "REJECTED"
    reason: str = ""
    adjusted_quantity: float = 0.0
    timestamp: int = 0
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> RiskDecision:
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_ms() -> int:
    """Current UTC time in milliseconds since epoch."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)
