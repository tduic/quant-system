"""Shared data models used across all services.

These dataclasses define the canonical event formats that flow through Kafka.
All timestamps are in milliseconds since epoch (UTC).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
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
    timestamp_exchange: int = 0  # ms since epoch
    timestamp_ingested: int = 0  # ms since epoch
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

    @classmethod
    def from_coinbase(cls, msg: dict, ingested_at: int) -> Trade:
        """Parse a Coinbase WebSocket match message.

        Coinbase 'match' format:
        {
            "type": "match",
            "trade_id": 123456,
            "product_id": "BTC-USD",
            "price": "42000.50",
            "size": "0.001",
            "side": "buy",       # taker side
            "time": "2026-03-21T12:00:00.000000Z"
        }
        """
        # Coinbase gives ISO timestamp — convert to epoch ms
        time_str = msg.get("time", "")
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            ts_ms = int(dt.timestamp() * 1000)
        except ValueError, AttributeError:
            ts_ms = ingested_at

        # Coinbase "side" is the taker's side.
        # is_buyer_maker = True when the taker is selling (maker was the buyer)
        taker_side = msg.get("side", "").lower()
        is_buyer_maker = taker_side == "sell"

        # Normalize product_id: "BTC-USD" -> "BTCUSD"
        product_id = msg.get("product_id", "")
        symbol = product_id.replace("-", "")

        return cls(
            exchange="coinbase",
            symbol=symbol,
            trade_id=msg.get("trade_id", 0),
            price=float(msg.get("price", 0)),
            quantity=float(msg.get("size", 0)),
            timestamp_exchange=ts_ms,
            timestamp_ingested=ingested_at,
            is_buyer_maker=is_buyer_maker,
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

    @classmethod
    def from_coinbase(cls, msg: dict, ingested_at: int) -> DepthUpdate:
        """Parse a Coinbase WebSocket l2update message.

        Coinbase 'l2update' format:
        {
            "type": "l2update",
            "product_id": "BTC-USD",
            "time": "2026-03-21T12:00:00.000000Z",
            "changes": [
                ["buy",  "42000.50", "0.5"],   // [side, price, new_size]
                ["sell", "42001.00", "0.3"],
            ]
        }
        """
        time_str = msg.get("time", "")
        try:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            ts_ms = int(dt.timestamp() * 1000)
        except ValueError, AttributeError:
            ts_ms = ingested_at

        product_id = msg.get("product_id", "")
        symbol = product_id.replace("-", "")

        bids = []
        asks = []
        for change in msg.get("changes", []):
            side, price, size = change[0], float(change[1]), float(change[2])
            if side == "buy":
                bids.append([price, size])
            else:
                asks.append([price, size])

        return cls(
            exchange="coinbase",
            symbol=symbol,
            first_update_id=0,
            final_update_id=0,
            bids=bids,
            asks=asks,
            timestamp_exchange=ts_ms,
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
    side: str = ""  # Side enum value
    strength: float = 0.0  # -1.0 to 1.0
    target_quantity: float = 0.0
    urgency: float = 0.5  # 0.0 to 1.0
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
    decision: str = ""  # "APPROVED" or "REJECTED"
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
    return int(datetime.now(UTC).timestamp() * 1000)
