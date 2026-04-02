"""Order lifecycle tracker.

Manages order state transitions and persists to Redis for durability.
Publishes status updates to Kafka for audit and post-trade consumption.

State machine:
    SUBMITTED → ACCEPTED → FILLED
    SUBMITTED → ACCEPTED → PARTIALLY_FILLED → FILLED
    SUBMITTED → REJECTED
    SUBMITTED → ACCEPTED → CANCELLED
"""

from __future__ import annotations

import json
import logging
import time

import redis as sync_redis

from quant_core.models import Order, OrderStatus, OrderStatusUpdate, now_ms

logger = logging.getLogger(__name__)


class OrderTracker:
    """Tracks order state in-memory with Redis persistence."""

    # Valid state transitions
    TRANSITIONS: dict[str, set[str]] = {
        OrderStatus.SUBMITTED: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
        OrderStatus.ACCEPTED: {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED},
        OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED},
    }

    def __init__(self, redis_client: sync_redis.Redis | None = None, run_id: str = "live") -> None:
        self._redis = redis_client
        self._run_id = run_id
        self._orders: dict[str, dict] = {}  # order_id -> order state

    def register_order(self, order: Order) -> None:
        """Register a new order with SUBMITTED status."""
        state = {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "status": OrderStatus.SUBMITTED,
            "filled_quantity": 0.0,
            "remaining_quantity": order.quantity,
            "avg_fill_price": 0.0,
            "exchange_order_id": "",
            "created_at": now_ms(),
            "updated_at": now_ms(),
            "strategy_id": order.strategy_id,
        }
        self._orders[order.order_id] = state
        self._persist(order.order_id, state)

    def transition(
        self,
        order_id: str,
        new_status: str,
        filled_quantity: float = 0.0,
        avg_fill_price: float = 0.0,
        exchange_order_id: str = "",
        reason: str = "",
    ) -> OrderStatusUpdate | None:
        """Attempt a state transition. Returns update event or None if invalid."""
        state = self._orders.get(order_id)
        if state is None:
            logger.warning("Order %s not found in tracker", order_id)
            return None

        current = state["status"]
        valid = self.TRANSITIONS.get(current, set())

        if new_status not in valid:
            logger.warning(
                "Invalid transition %s → %s for order %s",
                current,
                new_status,
                order_id,
            )
            return None

        # Update state
        state["status"] = new_status
        state["updated_at"] = now_ms()
        if exchange_order_id:
            state["exchange_order_id"] = exchange_order_id
        if filled_quantity > 0:
            state["filled_quantity"] = filled_quantity
            state["remaining_quantity"] = state["quantity"] - filled_quantity
        if avg_fill_price > 0:
            state["avg_fill_price"] = avg_fill_price

        self._persist(order_id, state)

        return OrderStatusUpdate(
            order_id=order_id,
            exchange_order_id=state["exchange_order_id"],
            status=new_status,
            filled_quantity=state["filled_quantity"],
            remaining_quantity=state["remaining_quantity"],
            avg_fill_price=state["avg_fill_price"],
            timestamp=now_ms(),
            reason=reason,
        )

    def get_order(self, order_id: str) -> dict | None:
        """Get current state of an order."""
        return self._orders.get(order_id)

    def get_open_orders(self) -> list[dict]:
        """Return all orders that are not in a terminal state."""
        terminal = {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
        return [o for o in self._orders.values() if o["status"] not in terminal]

    def _persist(self, order_id: str, state: dict) -> None:
        """Persist order state to Redis."""
        if self._redis is None:
            return
        try:
            key = f"orders:{self._run_id}:{order_id}"
            self._redis.set(key, json.dumps(state), ex=86400 * 7)  # 7 day TTL
        except Exception:
            logger.warning("Failed to persist order %s to Redis", order_id)
