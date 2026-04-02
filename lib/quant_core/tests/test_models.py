"""Tests for quant_core.models — shared event dataclasses."""

from __future__ import annotations

import json
import uuid

import pytest

from quant_core.models import (
    DepthUpdate,
    Fill,
    Order,
    OrderStatus,
    OrderStatusUpdate,
    OrderType,
    RiskDecision,
    Side,
    Signal,
    Trade,
    now_ms,
)

# -----------------------------------------------------------------------
# Fixtures: raw Binance messages
# -----------------------------------------------------------------------


@pytest.fixture
def binance_trade_msg() -> dict:
    """Realistic Binance WebSocket trade message."""
    return {
        "e": "trade",
        "E": 1672515782136,
        "s": "BTCUSDT",
        "t": 12345,
        "p": "42150.50",
        "q": "0.001",
        "b": 88,
        "a": 50,
        "T": 1672515782136,
        "m": True,
        "M": True,
    }


@pytest.fixture
def binance_depth_msg() -> dict:
    """Realistic Binance WebSocket depth update message."""
    return {
        "e": "depthUpdate",
        "E": 1672515782136,
        "s": "BTCUSDT",
        "U": 157,
        "u": 160,
        "b": [["42150.00", "1.5"], ["42149.50", "2.3"]],
        "a": [["42151.00", "0.8"], ["42151.50", "1.1"]],
    }


# -----------------------------------------------------------------------
# Trade
# -----------------------------------------------------------------------


class TestTrade:
    def test_from_binance_parses_all_fields(self, binance_trade_msg: dict):
        ingested_at = 1672515782140
        trade = Trade.from_binance(binance_trade_msg, ingested_at)

        assert trade.type == "trade"
        assert trade.exchange == "binance"
        assert trade.symbol == "BTCUSDT"
        assert trade.trade_id == 12345
        assert trade.price == pytest.approx(42150.50)
        assert trade.quantity == pytest.approx(0.001)
        assert trade.timestamp_exchange == 1672515782136
        assert trade.timestamp_ingested == 1672515782140
        assert trade.is_buyer_maker is True

    def test_from_binance_price_is_float_not_string(self, binance_trade_msg: dict):
        trade = Trade.from_binance(binance_trade_msg, 0)
        assert isinstance(trade.price, float)
        assert isinstance(trade.quantity, float)

    def test_to_json_roundtrip(self, binance_trade_msg: dict):
        original = Trade.from_binance(binance_trade_msg, 1672515782140)
        json_str = original.to_json()
        restored = Trade.from_json(json_str)

        assert restored.symbol == original.symbol
        assert restored.trade_id == original.trade_id
        assert restored.price == pytest.approx(original.price)
        assert restored.quantity == pytest.approx(original.quantity)
        assert restored.timestamp_exchange == original.timestamp_exchange
        assert restored.timestamp_ingested == original.timestamp_ingested
        assert restored.is_buyer_maker == original.is_buyer_maker

    def test_to_json_produces_valid_json(self, binance_trade_msg: dict):
        trade = Trade.from_binance(binance_trade_msg, 0)
        parsed = json.loads(trade.to_json())
        assert parsed["symbol"] == "BTCUSDT"
        assert parsed["type"] == "trade"

    def test_from_json_with_bytes(self, binance_trade_msg: dict):
        trade = Trade.from_binance(binance_trade_msg, 0)
        json_bytes = trade.to_json().encode()
        restored = Trade.from_json(json_bytes)
        assert restored.symbol == "BTCUSDT"

    def test_default_trade_has_sensible_defaults(self):
        trade = Trade()
        assert trade.type == "trade"
        assert trade.exchange == "binance"
        assert trade.price == 0.0
        assert trade.is_buyer_maker is False


# -----------------------------------------------------------------------
# Coinbase Trade parsing
# -----------------------------------------------------------------------


class TestTradeCoinbase:
    @pytest.fixture
    def coinbase_match(self) -> dict:
        return {
            "type": "match",
            "trade_id": 999,
            "product_id": "BTC-USD",
            "price": "42150.50",
            "size": "0.001",
            "side": "buy",
            "time": "2026-03-21T12:00:00.000000Z",
        }

    def test_from_coinbase_parses_all_fields(self, coinbase_match: dict):
        trade = Trade.from_coinbase(coinbase_match, 1672515782140)
        assert trade.exchange == "coinbase"
        assert trade.symbol == "BTCUSD"
        assert trade.trade_id == 999
        assert trade.price == pytest.approx(42150.50)
        assert trade.quantity == pytest.approx(0.001)
        assert trade.timestamp_ingested == 1672515782140

    def test_from_coinbase_buy_taker_means_not_buyer_maker(self, coinbase_match: dict):
        trade = Trade.from_coinbase(coinbase_match, 0)
        assert trade.is_buyer_maker is False

    def test_from_coinbase_sell_taker_means_buyer_maker(self, coinbase_match: dict):
        coinbase_match["side"] = "sell"
        trade = Trade.from_coinbase(coinbase_match, 0)
        assert trade.is_buyer_maker is True

    def test_from_coinbase_parses_iso_timestamp(self, coinbase_match: dict):
        trade = Trade.from_coinbase(coinbase_match, 0)
        assert trade.timestamp_exchange > 0

    def test_from_coinbase_symbol_strips_dash(self, coinbase_match: dict):
        coinbase_match["product_id"] = "ETH-USD"
        trade = Trade.from_coinbase(coinbase_match, 0)
        assert trade.symbol == "ETHUSD"

    def test_from_coinbase_roundtrip(self, coinbase_match: dict):
        original = Trade.from_coinbase(coinbase_match, 1000)
        restored = Trade.from_json(original.to_json())
        assert restored.symbol == "BTCUSD"
        assert restored.exchange == "coinbase"
        assert restored.price == pytest.approx(42150.50)


# -----------------------------------------------------------------------
# Coinbase DepthUpdate parsing
# -----------------------------------------------------------------------


class TestDepthUpdateCoinbase:
    @pytest.fixture
    def coinbase_l2update(self) -> dict:
        return {
            "type": "l2update",
            "product_id": "BTC-USD",
            "time": "2026-03-21T12:00:00.100000Z",
            "changes": [
                ["buy", "42150.00", "1.5"],
                ["sell", "42151.00", "0.8"],
            ],
        }

    def test_from_coinbase_parses_sides(self, coinbase_l2update: dict):
        depth = DepthUpdate.from_coinbase(coinbase_l2update, 0)
        assert len(depth.bids) == 1
        assert len(depth.asks) == 1
        assert depth.bids[0][0] == pytest.approx(42150.00)
        assert depth.asks[0][0] == pytest.approx(42151.00)

    def test_from_coinbase_symbol(self, coinbase_l2update: dict):
        depth = DepthUpdate.from_coinbase(coinbase_l2update, 0)
        assert depth.symbol == "BTCUSD"
        assert depth.exchange == "coinbase"

    def test_from_coinbase_empty_changes(self, coinbase_l2update: dict):
        coinbase_l2update["changes"] = []
        depth = DepthUpdate.from_coinbase(coinbase_l2update, 0)
        assert depth.bids == []
        assert depth.asks == []


# -----------------------------------------------------------------------
# DepthUpdate (Binance)
# -----------------------------------------------------------------------


class TestDepthUpdate:
    def test_from_binance_parses_all_fields(self, binance_depth_msg: dict):
        ingested_at = 1672515782140
        depth = DepthUpdate.from_binance(binance_depth_msg, ingested_at)

        assert depth.type == "depth_update"
        assert depth.exchange == "binance"
        assert depth.symbol == "BTCUSDT"
        assert depth.first_update_id == 157
        assert depth.final_update_id == 160
        assert depth.timestamp_exchange == 1672515782136
        assert depth.timestamp_ingested == 1672515782140

    def test_bids_asks_are_float_lists(self, binance_depth_msg: dict):
        depth = DepthUpdate.from_binance(binance_depth_msg, 0)

        assert len(depth.bids) == 2
        assert len(depth.asks) == 2
        assert depth.bids[0] == [pytest.approx(42150.00), pytest.approx(1.5)]
        assert depth.asks[0] == [pytest.approx(42151.00), pytest.approx(0.8)]

    def test_to_json_roundtrip(self, binance_depth_msg: dict):
        original = DepthUpdate.from_binance(binance_depth_msg, 1672515782140)
        json_str = original.to_json()
        restored = DepthUpdate.from_json(json_str)

        assert restored.symbol == original.symbol
        assert restored.first_update_id == original.first_update_id
        assert restored.final_update_id == original.final_update_id
        assert len(restored.bids) == len(original.bids)
        assert len(restored.asks) == len(original.asks)

    def test_empty_bids_asks(self):
        msg = {
            "e": "depthUpdate",
            "E": 1672515782136,
            "s": "BTCUSDT",
            "U": 1,
            "u": 2,
            "b": [],
            "a": [],
        }
        depth = DepthUpdate.from_binance(msg, 0)
        assert depth.bids == []
        assert depth.asks == []


# -----------------------------------------------------------------------
# Signal
# -----------------------------------------------------------------------


class TestSignal:
    def test_signal_generates_uuid(self):
        s1 = Signal()
        s2 = Signal()
        assert s1.signal_id != s2.signal_id
        # Should be valid UUID
        uuid.UUID(s1.signal_id)

    def test_signal_roundtrip(self):
        signal = Signal(
            strategy_id="mean_reversion_v1",
            symbol="BTCUSDT",
            side=Side.BUY.value,
            strength=0.75,
            target_quantity=0.001,
            urgency=0.8,
            mid_price_at_signal=42150.0,
            spread_at_signal=1.0,
        )
        restored = Signal.from_json(signal.to_json())
        assert restored.strategy_id == "mean_reversion_v1"
        assert restored.side == "BUY"
        assert restored.strength == pytest.approx(0.75)

    def test_signal_metadata_survives_roundtrip(self):
        signal = Signal(metadata={"reason": "vwap_deviation", "std_dev": 2.5})
        restored = Signal.from_json(signal.to_json())
        assert restored.metadata["reason"] == "vwap_deviation"
        assert restored.metadata["std_dev"] == pytest.approx(2.5)


# -----------------------------------------------------------------------
# Order
# -----------------------------------------------------------------------


class TestOrder:
    def test_order_defaults(self):
        order = Order()
        assert order.order_type == "MARKET"
        assert order.status == "SUBMITTED"
        uuid.UUID(order.order_id)  # valid UUID

    def test_order_roundtrip(self):
        order = Order(
            symbol="BTCUSDT",
            side=Side.BUY.value,
            order_type=OrderType.LIMIT.value,
            quantity=0.001,
            limit_price=42000.0,
            strategy_id="test",
        )
        restored = Order.from_json(order.to_json())
        assert restored.symbol == "BTCUSDT"
        assert restored.limit_price == pytest.approx(42000.0)
        assert restored.order_type == "LIMIT"


# -----------------------------------------------------------------------
# Fill
# -----------------------------------------------------------------------


class TestFill:
    def test_fill_roundtrip(self):
        fill = Fill(
            order_id="abc-123",
            symbol="BTCUSDT",
            side=Side.BUY.value,
            quantity=0.001,
            fill_price=42150.50,
            fee=0.04215,
            slippage_bps=0.5,
        )
        restored = Fill.from_json(fill.to_json())
        assert restored.order_id == "abc-123"
        assert restored.fill_price == pytest.approx(42150.50)
        assert restored.fee == pytest.approx(0.04215)
        assert restored.slippage_bps == pytest.approx(0.5)


# -----------------------------------------------------------------------
# RiskDecision
# -----------------------------------------------------------------------


class TestRiskDecision:
    def test_risk_decision_roundtrip(self):
        decision = RiskDecision(
            signal_id="sig-123",
            decision="APPROVED",
            reason="within_limits",
            adjusted_quantity=0.001,
            checks_passed=["position_size", "drawdown"],
            checks_failed=[],
        )
        restored = RiskDecision.from_json(decision.to_json())
        assert restored.decision == "APPROVED"
        assert restored.checks_passed == ["position_size", "drawdown"]
        assert restored.checks_failed == []


# -----------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------


class TestEnums:
    def test_side_values(self):
        assert Side.BUY.value == "BUY"
        assert Side.SELL.value == "SELL"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"

    def test_order_status_values(self):
        assert OrderStatus.SUBMITTED.value == "SUBMITTED"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.REJECTED.value == "REJECTED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.PARTIALLY_FILLED.value == "PARTIALLY_FILLED"


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


class TestOrderStatusUpdate:
    """Test OrderStatusUpdate dataclass for order status tracking."""

    def test_default_values(self):
        update = OrderStatusUpdate()
        assert update.order_id == ""
        assert update.exchange_order_id == ""
        assert update.status == ""
        assert update.filled_quantity == 0.0
        assert update.remaining_quantity == 0.0
        assert update.avg_fill_price == 0.0
        assert update.timestamp == 0
        assert update.reason == ""
        assert update.backtest_id is None

    def test_roundtrip_serialization_with_all_fields(self):
        original = OrderStatusUpdate(
            order_id="order-123",
            exchange_order_id="exchange-456",
            status=OrderStatus.PARTIALLY_FILLED.value,
            filled_quantity=0.5,
            remaining_quantity=0.5,
            avg_fill_price=42000.0,
            timestamp=1672515782136,
            reason="partial_fill",
            backtest_id="backtest-789",
        )
        json_str = original.to_json()
        restored = OrderStatusUpdate.from_json(json_str)

        assert restored.order_id == "order-123"
        assert restored.exchange_order_id == "exchange-456"
        assert restored.status == OrderStatus.PARTIALLY_FILLED.value
        assert restored.filled_quantity == pytest.approx(0.5)
        assert restored.remaining_quantity == pytest.approx(0.5)
        assert restored.avg_fill_price == pytest.approx(42000.0)
        assert restored.timestamp == 1672515782136
        assert restored.reason == "partial_fill"
        assert restored.backtest_id == "backtest-789"

    def test_to_json_produces_valid_json(self):
        update = OrderStatusUpdate(
            order_id="order-123",
            status="FILLED",
            filled_quantity=1.0,
        )
        json_str = update.to_json()
        parsed = json.loads(json_str)

        assert parsed["order_id"] == "order-123"
        assert parsed["status"] == "FILLED"
        assert parsed["filled_quantity"] == 1.0

    def test_from_json_with_bytes(self):
        original = OrderStatusUpdate(
            order_id="order-123",
            status="FILLED",
            filled_quantity=1.0,
            avg_fill_price=42150.50,
        )
        json_bytes = original.to_json().encode()
        restored = OrderStatusUpdate.from_json(json_bytes)

        assert restored.order_id == "order-123"
        assert restored.status == "FILLED"
        assert restored.avg_fill_price == pytest.approx(42150.50)

    def test_roundtrip_with_minimal_fields(self):
        original = OrderStatusUpdate(order_id="simple-order")
        restored = OrderStatusUpdate.from_json(original.to_json())

        assert restored.order_id == "simple-order"
        assert restored.exchange_order_id == ""
        assert restored.status == ""
        assert restored.filled_quantity == 0.0

    def test_roundtrip_preserves_float_precision(self):
        original = OrderStatusUpdate(
            order_id="order-123",
            avg_fill_price=42000.12345,
            filled_quantity=0.00012345,
        )
        restored = OrderStatusUpdate.from_json(original.to_json())

        assert restored.avg_fill_price == pytest.approx(42000.12345)
        assert restored.filled_quantity == pytest.approx(0.00012345)

    def test_roundtrip_preserves_large_timestamp(self):
        large_timestamp = 1704067200000
        original = OrderStatusUpdate(
            order_id="order-123",
            timestamp=large_timestamp,
        )
        restored = OrderStatusUpdate.from_json(original.to_json())

        assert restored.timestamp == large_timestamp

    def test_all_fields_survive_roundtrip(self):
        fields_to_test = {
            "order_id": "order-abc",
            "exchange_order_id": "exch-xyz",
            "status": OrderStatus.ACCEPTED.value,
            "filled_quantity": 0.75,
            "remaining_quantity": 0.25,
            "avg_fill_price": 42100.0,
            "timestamp": 1672515782136,
            "reason": "test_reason",
            "backtest_id": "test-backtest",
        }
        original = OrderStatusUpdate(**fields_to_test)
        json_str = original.to_json()
        restored = OrderStatusUpdate.from_json(json_str)

        for field_name, field_value in fields_to_test.items():
            restored_value = getattr(restored, field_name)
            if isinstance(field_value, float):
                assert restored_value == pytest.approx(field_value), f"Field {field_name} mismatch"
            else:
                assert restored_value == field_value, f"Field {field_name} mismatch"


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


class TestHelpers:
    def test_now_ms_returns_int(self):
        ts = now_ms()
        assert isinstance(ts, int)

    def test_now_ms_is_reasonable(self):
        ts = now_ms()
        # Should be after 2024-01-01 and before 2030-01-01
        assert 1704067200000 < ts < 1893456000000

    def test_now_ms_is_monotonic(self):
        t1 = now_ms()
        t2 = now_ms()
        assert t2 >= t1
