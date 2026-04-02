"""Unit tests for OrderTracker.

Tests cover:
- Order registration and initialization
- Valid state transitions
- Invalid state transitions
- Open orders filtering
- Quantity tracking
- Redis persistence (mocked)
- Non-persistence when Redis is None
"""

from __future__ import annotations

import json
from unittest import TestCase
from unittest.mock import MagicMock

import pytest

from execution_svc.order_tracker import OrderTracker
from quant_core.models import Order, OrderStatus, OrderStatusUpdate, Side, now_ms

# ============================================================================
# Test Fixtures / Helpers
# ============================================================================


def create_order(
    order_id: str = "order-1",
    symbol: str = "BTCUSD",
    side: str = Side.BUY,
    quantity: float = 1.0,
    strategy_id: str = "strat-1",
) -> Order:
    """Create a test Order."""
    return Order(
        order_id=order_id,
        timestamp=now_ms(),
        symbol=symbol,
        side=side,
        order_type="MARKET",
        quantity=quantity,
        status=OrderStatus.SUBMITTED,
        strategy_id=strategy_id,
    )


class TestOrderTrackerRegistration(TestCase):
    """Test order registration."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_register_order_creates_submitted_state(self):
        """Test that register_order creates an order with SUBMITTED status."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state is not None
        assert state["order_id"] == "order-1"
        assert state["symbol"] == "BTCUSD"
        assert state["side"] == Side.BUY
        assert state["quantity"] == 10.0
        assert state["status"] == OrderStatus.SUBMITTED
        assert state["filled_quantity"] == 0.0
        assert state["remaining_quantity"] == 10.0
        assert state["avg_fill_price"] == 0.0
        assert state["exchange_order_id"] == ""
        assert state["strategy_id"] == "strat-1"

    def test_register_order_sets_timestamps(self):
        """Test that register_order sets created_at and updated_at."""
        order = create_order()
        before = now_ms()
        self.tracker.register_order(order)
        after = now_ms()

        state = self.tracker.get_order("order-1")
        assert state is not None
        assert before <= state["created_at"] <= after
        assert before <= state["updated_at"] <= after

    def test_register_multiple_orders(self):
        """Test registering multiple orders."""
        order1 = create_order(order_id="order-1")
        order2 = create_order(order_id="order-2")

        self.tracker.register_order(order1)
        self.tracker.register_order(order2)

        assert self.tracker.get_order("order-1") is not None
        assert self.tracker.get_order("order-2") is not None


# ============================================================================
# Test Valid Transitions
# ============================================================================


class TestValidTransitions(TestCase):
    """Test valid state transitions."""

    def setUp(self):
        self.tracker = OrderTracker()
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

    def test_transition_submitted_to_accepted(self):
        """Test SUBMITTED → ACCEPTED transition."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exchange-123",
        )

        assert result is not None
        assert isinstance(result, OrderStatusUpdate)
        assert result.order_id == "order-1"
        assert result.status == OrderStatus.ACCEPTED
        assert result.exchange_order_id == "exchange-123"
        assert result.filled_quantity == 0.0
        assert result.remaining_quantity == 10.0

        # Verify state was updated
        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.ACCEPTED
        assert state["exchange_order_id"] == "exchange-123"

    def test_transition_submitted_to_rejected(self):
        """Test SUBMITTED → REJECTED transition."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.REJECTED,
            reason="insufficient_funds",
        )

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert result.reason == "insufficient_funds"

        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.REJECTED

    def test_transition_accepted_to_filled(self):
        """Test ACCEPTED → FILLED transition with fill data."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exchange-123",
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
            avg_fill_price=45000.0,
        )

        assert result is not None
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 10.0
        assert result.remaining_quantity == 0.0
        assert result.avg_fill_price == 45000.0

        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.FILLED
        assert state["filled_quantity"] == 10.0
        assert state["remaining_quantity"] == 0.0
        assert state["avg_fill_price"] == 45000.0

    def test_transition_accepted_to_partially_filled(self):
        """Test ACCEPTED → PARTIALLY_FILLED transition."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exchange-123",
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
            avg_fill_price=45000.0,
        )

        assert result is not None
        assert result.status == OrderStatus.PARTIALLY_FILLED
        assert result.filled_quantity == 5.0
        assert result.remaining_quantity == 5.0

        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.PARTIALLY_FILLED
        assert state["filled_quantity"] == 5.0
        assert state["remaining_quantity"] == 5.0

    def test_transition_partially_filled_to_filled(self):
        """Test PARTIALLY_FILLED → FILLED transition."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
            avg_fill_price=45000.0,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
            avg_fill_price=45050.0,
        )

        assert result is not None
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == 10.0
        assert result.remaining_quantity == 0.0

    def test_transition_partially_filled_to_partially_filled(self):
        """Test PARTIALLY_FILLED → PARTIALLY_FILLED (incremental fills)."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=3.0,
            avg_fill_price=45000.0,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=7.0,
            avg_fill_price=45025.0,
        )

        assert result is not None
        assert result.filled_quantity == 7.0
        assert result.remaining_quantity == 3.0

    def test_transition_accepted_to_cancelled(self):
        """Test ACCEPTED → CANCELLED transition."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.CANCELLED,
            reason="user_cancelled",
        )

        assert result is not None
        assert result.status == OrderStatus.CANCELLED
        assert result.reason == "user_cancelled"

    def test_transition_partially_filled_to_cancelled(self):
        """Test PARTIALLY_FILLED → CANCELLED transition."""
        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=3.0,
            avg_fill_price=45000.0,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.CANCELLED,
            reason="user_cancelled",
        )

        assert result is not None
        assert result.status == OrderStatus.CANCELLED


# ============================================================================
# Test Invalid Transitions
# ============================================================================


class TestInvalidTransitions(TestCase):
    """Test that invalid transitions return None."""

    def setUp(self):
        self.tracker = OrderTracker()
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

    def test_transition_submitted_to_filled_invalid(self):
        """Test that SUBMITTED → FILLED is invalid."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
        )
        assert result is None

        # Order should remain in SUBMITTED state
        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.SUBMITTED

    def test_transition_submitted_to_partially_filled_invalid(self):
        """Test that SUBMITTED → PARTIALLY_FILLED is invalid."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
        )
        assert result is None
        assert self.tracker.get_order("order-1")["status"] == OrderStatus.SUBMITTED

    def test_transition_submitted_to_cancelled_invalid(self):
        """Test that SUBMITTED → CANCELLED is invalid."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.CANCELLED,
        )
        assert result is None

    def test_transition_from_filled_invalid(self):
        """Test that transitions from FILLED terminal state are invalid."""
        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.CANCELLED,
        )
        assert result is None

    def test_transition_from_rejected_invalid(self):
        """Test that transitions from REJECTED terminal state are invalid."""
        self.tracker.transition(order_id="order-1", new_status=OrderStatus.REJECTED)

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )
        assert result is None

    def test_transition_from_cancelled_invalid(self):
        """Test that transitions from CANCELLED terminal state are invalid."""
        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.CANCELLED,
        )

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
        )
        assert result is None


# ============================================================================
# Test Nonexistent Orders
# ============================================================================


class TestNonexistentOrders(TestCase):
    """Test behavior with nonexistent orders."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_transition_on_nonexistent_order_returns_none(self):
        """Test that transitioning a nonexistent order returns None."""
        result = self.tracker.transition(
            order_id="nonexistent-order",
            new_status=OrderStatus.ACCEPTED,
        )
        assert result is None

    def test_get_order_nonexistent_returns_none(self):
        """Test that get_order returns None for unknown order."""
        result = self.tracker.get_order("nonexistent-order")
        assert result is None


# ============================================================================
# Test Open Orders Filtering
# ============================================================================


class TestOpenOrdersFiltering(TestCase):
    """Test get_open_orders filtering."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_get_open_orders_excludes_filled(self):
        """Test that FILLED orders are excluded from open orders."""
        order = create_order(order_id="filled-order", quantity=10.0)
        self.tracker.register_order(order)
        self.tracker.transition(
            order_id="filled-order",
            new_status=OrderStatus.ACCEPTED,
        )
        self.tracker.transition(
            order_id="filled-order",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
        )

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 0

    def test_get_open_orders_excludes_rejected(self):
        """Test that REJECTED orders are excluded from open orders."""
        order = create_order(order_id="rejected-order")
        self.tracker.register_order(order)
        self.tracker.transition(
            order_id="rejected-order",
            new_status=OrderStatus.REJECTED,
        )

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 0

    def test_get_open_orders_excludes_cancelled(self):
        """Test that CANCELLED orders are excluded from open orders."""
        order = create_order(order_id="cancelled-order")
        self.tracker.register_order(order)
        self.tracker.transition(
            order_id="cancelled-order",
            new_status=OrderStatus.ACCEPTED,
        )
        self.tracker.transition(
            order_id="cancelled-order",
            new_status=OrderStatus.CANCELLED,
        )

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 0

    def test_get_open_orders_includes_submitted(self):
        """Test that SUBMITTED orders are included in open orders."""
        order = create_order(order_id="submitted-order")
        self.tracker.register_order(order)

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == "submitted-order"
        assert open_orders[0]["status"] == OrderStatus.SUBMITTED

    def test_get_open_orders_includes_accepted(self):
        """Test that ACCEPTED orders are included in open orders."""
        order = create_order(order_id="accepted-order")
        self.tracker.register_order(order)
        self.tracker.transition(
            order_id="accepted-order",
            new_status=OrderStatus.ACCEPTED,
        )

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == "accepted-order"
        assert open_orders[0]["status"] == OrderStatus.ACCEPTED

    def test_get_open_orders_includes_partially_filled(self):
        """Test that PARTIALLY_FILLED orders are included in open orders."""
        order = create_order(order_id="partial-order", quantity=10.0)
        self.tracker.register_order(order)
        self.tracker.transition(
            order_id="partial-order",
            new_status=OrderStatus.ACCEPTED,
        )
        self.tracker.transition(
            order_id="partial-order",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
        )

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == "partial-order"
        assert open_orders[0]["status"] == OrderStatus.PARTIALLY_FILLED

    def test_get_open_orders_mixed_statuses(self):
        """Test get_open_orders with mixed order statuses."""
        # Create multiple orders in different states
        order1 = create_order(order_id="order-1")
        order2 = create_order(order_id="order-2")
        order3 = create_order(order_id="order-3")
        order4 = create_order(order_id="order-4")
        order5 = create_order(order_id="order-5", quantity=10.0)

        self.tracker.register_order(order1)
        self.tracker.register_order(order2)
        self.tracker.register_order(order3)
        self.tracker.register_order(order4)
        self.tracker.register_order(order5)

        # order1: SUBMITTED (open)
        # order2: ACCEPTED (open)
        self.tracker.transition(order_id="order-2", new_status=OrderStatus.ACCEPTED)

        # order3: FILLED (closed)
        self.tracker.transition(order_id="order-3", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-3",
            new_status=OrderStatus.FILLED,
            filled_quantity=1.0,
        )

        # order4: REJECTED (closed)
        self.tracker.transition(order_id="order-4", new_status=OrderStatus.REJECTED)

        # order5: PARTIALLY_FILLED (open)
        self.tracker.transition(order_id="order-5", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-5",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
        )

        open_orders = self.tracker.get_open_orders()
        open_ids = {o["order_id"] for o in open_orders}

        assert len(open_orders) == 3
        assert open_ids == {"order-1", "order-2", "order-5"}


# ============================================================================
# Test Quantity Tracking
# ============================================================================


class TestQuantityTracking(TestCase):
    """Test fill_quantity and remaining_quantity tracking."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_fill_quantity_remaining_quantity_on_full_fill(self):
        """Test fill_quantity and remaining_quantity on full fill."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 0.0
        assert state["remaining_quantity"] == 10.0

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
        )

        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 10.0
        assert state["remaining_quantity"] == 0.0

    def test_fill_quantity_remaining_quantity_on_partial_fill(self):
        """Test fill_quantity and remaining_quantity on partial fill."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=3.5,
        )

        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 3.5
        assert state["remaining_quantity"] == 6.5

    def test_fill_quantity_incremental_updates(self):
        """Test fill_quantity updates through multiple partial fills."""
        order = create_order(order_id="order-1", quantity=100.0)
        self.tracker.register_order(order)

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)

        # First fill: 30 units
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=30.0,
        )
        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 30.0
        assert state["remaining_quantity"] == 70.0

        # Second fill: 50 units
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=50.0,
        )
        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 50.0
        assert state["remaining_quantity"] == 50.0

        # Final fill: 100 units
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=100.0,
        )
        state = self.tracker.get_order("order-1")
        assert state["filled_quantity"] == 100.0
        assert state["remaining_quantity"] == 0.0


# ============================================================================
# Test avg_fill_price Tracking
# ============================================================================


class TestAvgFillPriceTracking(TestCase):
    """Test average fill price tracking."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_avg_fill_price_on_full_fill(self):
        """Test avg_fill_price is set on full fill."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state["avg_fill_price"] == 0.0

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
            avg_fill_price=45000.0,
        )

        state = self.tracker.get_order("order-1")
        assert state["avg_fill_price"] == 45000.0

    def test_avg_fill_price_on_partial_fill(self):
        """Test avg_fill_price is set on partial fill."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
            avg_fill_price=44999.5,
        )

        state = self.tracker.get_order("order-1")
        assert state["avg_fill_price"] == 44999.5

    def test_avg_fill_price_zero_not_updated(self):
        """Test that avg_fill_price is not updated if passed as 0."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
            avg_fill_price=45000.0,
        )

        # Transition with 0 price should not update
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=8.0,
            avg_fill_price=0.0,
        )

        state = self.tracker.get_order("order-1")
        # Price should remain at 45000.0 because 0.0 was not accepted
        assert state["avg_fill_price"] == 45000.0


# ============================================================================
# Test Redis Persistence (Mocked)
# ============================================================================


class TestRedisPersistence(TestCase):
    """Test Redis persistence with mocked redis_client."""

    def test_persist_on_register_order(self):
        """Test that register_order calls redis.set with correct key and TTL."""
        mock_redis = MagicMock()
        tracker = OrderTracker(redis_client=mock_redis, run_id="test-run")

        order = create_order(order_id="order-1", quantity=10.0)
        tracker.register_order(order)

        # Verify redis.set was called
        assert mock_redis.set.called
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        value = call_args[0][1]
        ttl = call_args[1]["ex"]

        assert key == "orders:test-run:order-1"
        assert isinstance(value, str)
        # Verify value is valid JSON
        data = json.loads(value)
        assert data["order_id"] == "order-1"
        assert data["status"] == OrderStatus.SUBMITTED
        assert ttl == 86400 * 7  # 7 day TTL

    def test_persist_on_transition(self):
        """Test that transition calls redis.set."""
        mock_redis = MagicMock()
        tracker = OrderTracker(redis_client=mock_redis, run_id="test-run")

        order = create_order(order_id="order-1")
        tracker.register_order(order)
        mock_redis.reset_mock()  # Reset call count from register

        tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exchange-123",
        )

        assert mock_redis.set.called
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        value = call_args[0][1]

        assert key == "orders:test-run:order-1"
        data = json.loads(value)
        assert data["status"] == OrderStatus.ACCEPTED
        assert data["exchange_order_id"] == "exchange-123"

    def test_persist_uses_run_id(self):
        """Test that persist uses run_id in the key."""
        mock_redis = MagicMock()
        tracker = OrderTracker(redis_client=mock_redis, run_id="custom-run-123")

        order = create_order(order_id="order-abc")
        tracker.register_order(order)

        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        assert key == "orders:custom-run-123:order-abc"

    def test_persist_with_multiple_transitions(self):
        """Test redis.set is called on each transition."""
        mock_redis = MagicMock()
        tracker = OrderTracker(redis_client=mock_redis, run_id="test-run")

        order = create_order(order_id="order-1", quantity=10.0)
        tracker.register_order(order)

        # First transition
        tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        call_count_after_accept = mock_redis.set.call_count

        # Second transition
        tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=5.0,
        )
        call_count_after_partial = mock_redis.set.call_count

        # Third transition
        tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
        )
        call_count_after_filled = mock_redis.set.call_count

        # Each should have incremented the call count
        assert call_count_after_accept > 1
        assert call_count_after_partial > call_count_after_accept
        assert call_count_after_filled > call_count_after_partial


# ============================================================================
# Test No Redis (None)
# ============================================================================


class TestNoRedis(TestCase):
    """Test that tracker works without Redis (redis_client=None)."""

    def setUp(self):
        self.tracker = OrderTracker(redis_client=None)

    def test_register_order_without_redis(self):
        """Test register_order works when redis_client is None."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state is not None
        assert state["order_id"] == "order-1"

    def test_transition_without_redis(self):
        """Test transition works when redis_client is None."""
        order = create_order(order_id="order-1")
        self.tracker.register_order(order)

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )

        assert result is not None
        assert result.status == OrderStatus.ACCEPTED

    def test_get_open_orders_without_redis(self):
        """Test get_open_orders works when redis_client is None."""
        order1 = create_order(order_id="order-1")
        order2 = create_order(order_id="order-2")

        self.tracker.register_order(order1)
        self.tracker.register_order(order2)

        self.tracker.transition(order_id="order-2", new_status=OrderStatus.REJECTED)

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0]["order_id"] == "order-1"

    def test_full_lifecycle_without_redis(self):
        """Test full order lifecycle without Redis."""
        order = create_order(order_id="order-1", quantity=10.0)
        self.tracker.register_order(order)

        # SUBMITTED → ACCEPTED
        result1 = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exch-123",
        )
        assert result1 is not None

        # ACCEPTED → PARTIALLY_FILLED
        result2 = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=6.0,
            avg_fill_price=45000.0,
        )
        assert result2 is not None

        # PARTIALLY_FILLED → FILLED
        result3 = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=10.0,
            avg_fill_price=45010.0,
        )
        assert result3 is not None

        state = self.tracker.get_order("order-1")
        assert state["status"] == OrderStatus.FILLED
        assert state["filled_quantity"] == 10.0
        assert state["remaining_quantity"] == 0.0


# ============================================================================
# Test Order Status Update Return Values
# ============================================================================


class TestOrderStatusUpdateReturn(TestCase):
    """Test OrderStatusUpdate return values."""

    def setUp(self):
        self.tracker = OrderTracker()
        order = create_order(order_id="order-1", quantity=100.0)
        self.tracker.register_order(order)

    def test_status_update_has_correct_attributes(self):
        """Test that returned OrderStatusUpdate has all correct attributes."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exch-456",
        )

        assert isinstance(result, OrderStatusUpdate)
        assert result.order_id == "order-1"
        assert result.status == OrderStatus.ACCEPTED
        assert result.exchange_order_id == "exch-456"
        assert result.filled_quantity == 0.0
        assert result.remaining_quantity == 100.0
        assert result.avg_fill_price == 0.0
        assert isinstance(result.timestamp, int)
        assert result.timestamp > 0

    def test_status_update_with_fill_data(self):
        """Test OrderStatusUpdate contains correct fill data."""
        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)

        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=25.5,
            avg_fill_price=44999.0,
            reason="partial_fill",
        )

        assert result.filled_quantity == 25.5
        assert result.remaining_quantity == 74.5
        assert result.avg_fill_price == 44999.0
        assert result.reason == "partial_fill"

    def test_status_update_with_reason(self):
        """Test OrderStatusUpdate includes reason."""
        result = self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.REJECTED,
            reason="insufficient_funds",
        )

        assert result is not None
        assert result.reason == "insufficient_funds"


# ============================================================================
# Test Exchange Order ID Handling
# ============================================================================


class TestExchangeOrderIDHandling(TestCase):
    """Test exchange_order_id tracking and updates."""

    def setUp(self):
        self.tracker = OrderTracker()
        order = create_order(order_id="order-1")
        self.tracker.register_order(order)

    def test_exchange_order_id_set_on_transition(self):
        """Test that exchange_order_id is set during transition."""
        state = self.tracker.get_order("order-1")
        assert state["exchange_order_id"] == ""

        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exch-789",
        )

        state = self.tracker.get_order("order-1")
        assert state["exchange_order_id"] == "exch-789"

    def test_exchange_order_id_not_overwritten_with_empty(self):
        """Test that exchange_order_id is not overwritten with empty string."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exch-first",
        )

        # Transition without providing exchange_order_id
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=0.5,
            exchange_order_id="",  # Empty
        )

        state = self.tracker.get_order("order-1")
        # Should still have the original value because empty is falsy
        assert state["exchange_order_id"] == "exch-first"

    def test_exchange_order_id_updated_with_new_value(self):
        """Test that exchange_order_id can be updated with new value."""
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
            exchange_order_id="exch-old",
        )

        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=0.5,
            exchange_order_id="exch-new",
        )

        state = self.tracker.get_order("order-1")
        assert state["exchange_order_id"] == "exch-new"


# ============================================================================
# Test Timestamp Updates
# ============================================================================


class TestTimestampUpdates(TestCase):
    """Test that timestamps are properly updated."""

    def setUp(self):
        self.tracker = OrderTracker()
        order = create_order(order_id="order-1")
        self.tracker.register_order(order)

    def test_updated_at_changes_on_transition(self):
        """Test that updated_at timestamp changes after transition."""
        state1 = self.tracker.get_order("order-1")
        updated_at_1 = state1["updated_at"]

        # Wait a moment (though in fast tests this might be minimal)
        import time

        time.sleep(0.01)

        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )

        state2 = self.tracker.get_order("order-1")
        updated_at_2 = state2["updated_at"]

        # updated_at should be later than before
        assert updated_at_2 >= updated_at_1

    def test_created_at_unchanged_on_transition(self):
        """Test that created_at never changes."""
        state1 = self.tracker.get_order("order-1")
        created_at = state1["created_at"]

        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.ACCEPTED,
        )

        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=0.5,
        )

        state2 = self.tracker.get_order("order-1")
        assert state2["created_at"] == created_at


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases(TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        self.tracker = OrderTracker()

    def test_zero_quantity_order(self):
        """Test handling of zero-quantity order."""
        order = create_order(order_id="order-1", quantity=0.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state["quantity"] == 0.0
        assert state["remaining_quantity"] == 0.0

    def test_fractional_quantity(self):
        """Test handling of fractional quantities."""
        order = create_order(order_id="order-1", quantity=0.00001)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state["quantity"] == 0.00001
        assert state["remaining_quantity"] == 0.00001

    def test_large_quantity(self):
        """Test handling of large quantities."""
        order = create_order(order_id="order-1", quantity=1_000_000.0)
        self.tracker.register_order(order)

        state = self.tracker.get_order("order-1")
        assert state["quantity"] == 1_000_000.0

    def test_high_precision_fill_price(self):
        """Test handling of high precision fill prices."""
        order = create_order(order_id="order-1", quantity=1.0)
        self.tracker.register_order(order)

        self.tracker.transition(order_id="order-1", new_status=OrderStatus.ACCEPTED)
        self.tracker.transition(
            order_id="order-1",
            new_status=OrderStatus.FILLED,
            filled_quantity=1.0,
            avg_fill_price=45123.456789,
        )

        state = self.tracker.get_order("order-1")
        assert state["avg_fill_price"] == 45123.456789

    def test_multiple_same_symbol_orders(self):
        """Test multiple orders for the same symbol."""
        order1 = create_order(order_id="order-1", symbol="BTCUSD")
        order2 = create_order(order_id="order-2", symbol="BTCUSD")
        order3 = create_order(order_id="order-3", symbol="ETHUSD")

        self.tracker.register_order(order1)
        self.tracker.register_order(order2)
        self.tracker.register_order(order3)

        state1 = self.tracker.get_order("order-1")
        state2 = self.tracker.get_order("order-2")
        state3 = self.tracker.get_order("order-3")

        assert state1["symbol"] == "BTCUSD"
        assert state2["symbol"] == "BTCUSD"
        assert state3["symbol"] == "ETHUSD"

        open_orders = self.tracker.get_open_orders()
        assert len(open_orders) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
