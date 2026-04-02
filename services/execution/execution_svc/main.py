"""Execution Service — entry point.

Receives approved orders from the Risk Gateway, simulates fills
(paper trading) or routes to Coinbase REST (live trading),
and publishes fill events + order status updates.

Includes circuit breaker check — when tripped, orders are rejected
and no fills are generated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from execution_svc.fill_simulator import FillSimulator
from execution_svc.order_tracker import OrderTracker
from quant_core.circuit_breaker import CircuitBreaker
from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    TOPIC_AUDIT,
    TOPIC_FILLS,
    TOPIC_HEARTBEAT,
    TOPIC_ORDERS,
    TOPIC_ORDER_STATUS,
    TOPIC_RAW_DEPTH,
    QConsumer,
    QProducer,
)
from quant_core.logging import setup_logging
from quant_core.metrics import MetricsRegistry
from quant_core.models import DepthUpdate, Order, OrderStatus, now_ms
from quant_core.redis_utils import create_sync_redis

logger = logging.getLogger(__name__)

SERVICE_NAME = "execution"

# Default market data if no book state available
DEFAULT_SPREAD = 1.0


def _emit_audit(producer: QProducer, event_type: str, detail: dict) -> None:
    """Publish an audit event."""
    producer.produce(
        topic=TOPIC_AUDIT,
        key=SERVICE_NAME,
        value=json.dumps({
            "service": SERVICE_NAME,
            "event": event_type,
            "timestamp": now_ms(),
            **detail,
        }),
    )


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Execution Service")

    run_id = config.backtest_id or "live"
    trading_mode = os.getenv("TRADING_MODE", "paper")  # "paper" or "live"

    # --- Redis ---
    redis_client = create_sync_redis(config.redis)

    # --- Metrics ---
    metrics = MetricsRegistry(SERVICE_NAME)
    metrics.start_http_server(port=9090)

    # --- Circuit breaker ---
    cb = CircuitBreaker(redis_client, run_id=run_id)

    # --- Order tracker ---
    tracker = OrderTracker(redis_client=redis_client, run_id=run_id)

    # --- Kafka ---
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)

    # Consumer for orders AND depth (to get current mid/spread)
    consumer = QConsumer(
        config.kafka,
        group_id="execution",
        topics=[TOPIC_ORDERS, TOPIC_RAW_DEPTH],
    )

    # --- Fill simulator (paper trading) ---
    simulator = FillSimulator()

    # --- Coinbase REST client (live trading) ---
    live_client = None
    if trading_mode == "live":
        try:
            from quant_core.coinbase_rest import CoinbaseRESTClient

            live_client = CoinbaseRESTClient.from_env()
            logger.info("Live trading mode enabled — Coinbase REST client initialized")
        except Exception:
            logger.exception("Failed to initialize Coinbase REST client, falling back to paper trading")
            trading_mode = "paper"

    logger.info("Trading mode: %s", trading_mode)

    # --- Track latest mid/spread per symbol ---
    latest_mid: dict[str, float] = {}
    latest_spread: dict[str, float] = {}

    # --- Counters ---
    fill_count = 0
    breaker_blocked = 0

    # --- Graceful shutdown ---
    shutdown_event = asyncio.Event()

    def handle_signal_os(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal_os)
    signal.signal(signal.SIGINT, handle_signal_os)

    # --- Heartbeat ---
    async def heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            producer.produce(
                topic=TOPIC_HEARTBEAT,
                key=SERVICE_NAME,
                value=json.dumps({
                    "service": SERVICE_NAME,
                    "timestamp": now_ms(),
                    "fills": fill_count,
                    "trading_mode": trading_mode,
                    "breaker_blocked": breaker_blocked,
                }),
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    def consume_loop() -> None:
        nonlocal fill_count, breaker_blocked

        while not shutdown_event.is_set():
            msg = consumer.poll(timeout=0.1)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            topic = msg.topic()
            value = msg.value()

            if topic == TOPIC_RAW_DEPTH:
                # Update latest mid/spread for this symbol
                try:
                    depth = DepthUpdate.from_json(value)
                    symbol = depth.symbol.upper()
                    if depth.bids and depth.asks:
                        best_bid = max(b[0] for b in depth.bids)
                        best_ask = min(a[0] for a in depth.asks)
                        latest_mid[symbol] = (best_bid + best_ask) / 2.0
                        latest_spread[symbol] = best_ask - best_bid
                except Exception:
                    pass
                continue

            if topic == TOPIC_ORDERS:
                try:
                    order = Order.from_json(value)
                except Exception:
                    logger.warning("Failed to parse order")
                    continue

                # --- Circuit breaker check ---
                if cb.is_tripped():
                    breaker_blocked += 1
                    metrics.inc("orders_breaker_blocked")
                    metrics.set_gauge("circuit_breaker_active", 1.0)
                    _emit_audit(producer, "order_blocked_breaker", {
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                    })
                    if breaker_blocked % 100 == 1:
                        logger.warning("Circuit breaker active — blocked %d orders", breaker_blocked)
                    producer.poll(0.0)
                    continue

                symbol = order.symbol.upper()
                mid = latest_mid.get(symbol)
                spread = latest_spread.get(symbol, DEFAULT_SPREAD)

                if mid is None:
                    logger.warning("No market data for %s, skipping order %s", symbol, order.order_id)
                    continue

                # Register order and transition to ACCEPTED
                tracker.register_order(order)
                accepted_update = tracker.transition(order.order_id, OrderStatus.ACCEPTED)
                if accepted_update:
                    producer.produce(
                        topic=TOPIC_ORDER_STATUS,
                        key=order.symbol,
                        value=accepted_update.to_json(),
                    )

                # --- Execute (paper or live) ---
                if trading_mode == "live" and live_client is not None:
                    # Live trading path — place real order on Coinbase
                    try:
                        exchange_result = live_client.place_order(
                            symbol=order.symbol,
                            side=order.side.lower(),
                            size=str(order.quantity),
                            order_type="market",
                        )
                        exchange_order_id = exchange_result.get("id", "")
                        _emit_audit(producer, "order_sent_exchange", {
                            "order_id": order.order_id,
                            "exchange_order_id": exchange_order_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "quantity": order.quantity,
                        })
                        logger.info(
                            "Order sent to exchange: %s → %s",
                            order.order_id,
                            exchange_order_id,
                        )
                        # Fill event will come from exchange polling
                        # For now, we still simulate the fill immediately
                        fill = simulator.simulate_fill(
                            order=order, mid_price=mid, spread=spread,
                        )
                    except Exception:
                        logger.exception("Failed to place order %s on exchange", order.order_id)
                        tracker.transition(
                            order.order_id,
                            OrderStatus.REJECTED,
                            reason="exchange_error",
                        )
                        continue
                else:
                    # Paper trading path
                    fill = simulator.simulate_fill(
                        order=order, mid_price=mid, spread=spread,
                    )

                # Transition to FILLED
                filled_update = tracker.transition(
                    order.order_id,
                    OrderStatus.FILLED,
                    filled_quantity=fill.quantity,
                    avg_fill_price=fill.fill_price,
                )
                if filled_update:
                    producer.produce(
                        topic=TOPIC_ORDER_STATUS,
                        key=order.symbol,
                        value=filled_update.to_json(),
                    )

                metrics.set_gauge("circuit_breaker_active", 0.0)

                # Publish fill
                producer.produce(
                    topic=TOPIC_FILLS,
                    key=fill.symbol,
                    value=fill.to_json(),
                )
                fill_count += 1
                metrics.inc("fills_total", labels={"symbol": fill.symbol, "side": fill.side, "mode": trading_mode})
                metrics.observe("fill_slippage_bps", fill.slippage_bps, labels={"symbol": fill.symbol})
                metrics.observe("fill_fee", fill.fee, labels={"symbol": fill.symbol})
                metrics.set_gauge("latest_fill_price", fill.fill_price, labels={"symbol": fill.symbol})

                _emit_audit(producer, "fill_generated", {
                    "fill_id": fill.fill_id,
                    "order_id": order.order_id,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "quantity": fill.quantity,
                    "fill_price": fill.fill_price,
                    "fee": fill.fee,
                    "slippage_bps": fill.slippage_bps,
                    "trading_mode": trading_mode,
                })

                logger.info(
                    "Fill: %s %s %.6f @ %.2f (slippage=%.2f bps, fee=%.4f) [%s]",
                    fill.side,
                    fill.symbol,
                    fill.quantity,
                    fill.fill_price,
                    fill.slippage_bps,
                    fill.fee,
                    trading_mode,
                )

            producer.poll(0.0)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, consume_loop)

    await shutdown_event.wait()

    heartbeat_task.cancel()
    consumer.close()
    producer.flush(timeout=5.0)
    logger.info("Execution Service stopped. Fills: %d", fill_count)


if __name__ == "__main__":
    asyncio.run(main())
