"""Execution Service — entry point.

Receives approved orders from the Risk Gateway, simulates fills
(paper trading), and publishes fill events.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from execution_svc.fill_simulator import FillSimulator
from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    TOPIC_FILLS,
    TOPIC_HEARTBEAT,
    TOPIC_ORDERS,
    TOPIC_RAW_DEPTH,
    QConsumer,
    QProducer,
)
from quant_core.logging import setup_logging
from quant_core.models import DepthUpdate, Order, now_ms

logger = logging.getLogger(__name__)

SERVICE_NAME = "execution"

# Default market data if no book state available
DEFAULT_SPREAD = 1.0


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Execution Service")

    # --- Kafka ---
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)

    # Consumer for orders AND depth (to get current mid/spread)
    consumer = QConsumer(
        config.kafka,
        group_id="execution",
        topics=[TOPIC_ORDERS, TOPIC_RAW_DEPTH],
    )

    # --- Fill simulator ---
    simulator = FillSimulator()

    # --- Track latest mid/spread per symbol ---
    latest_mid: dict[str, float] = {}
    latest_spread: dict[str, float] = {}

    # --- Counters ---
    fill_count = 0

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
                value=f'{{"service":"{SERVICE_NAME}","timestamp":{now_ms()},"fills":{fill_count}}}',
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    def consume_loop() -> None:
        nonlocal fill_count

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

                symbol = order.symbol.upper()
                mid = latest_mid.get(symbol)
                spread = latest_spread.get(symbol, DEFAULT_SPREAD)

                if mid is None:
                    logger.warning("No market data for %s, skipping order %s", symbol, order.order_id)
                    continue

                fill = simulator.simulate_fill(
                    order=order,
                    mid_price=mid,
                    spread=spread,
                )

                producer.produce(
                    topic=TOPIC_FILLS,
                    key=fill.symbol,
                    value=fill.to_json(),
                )
                fill_count += 1

                logger.info(
                    "Fill: %s %s %.6f @ %.2f (slippage=%.2f bps, fee=%.4f)",
                    fill.side,
                    fill.symbol,
                    fill.quantity,
                    fill.fill_price,
                    fill.slippage_bps,
                    fill.fee,
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
