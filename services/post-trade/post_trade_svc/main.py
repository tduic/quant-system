"""Post-Trade Analysis Service — entry point.

Consumes fills + trade data from Kafka, computes real-time analytics,
and serves a FastAPI dashboard on port 8080 with Excel export.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading

import uvicorn

from post_trade_svc.dashboard import create_app
from post_trade_svc.state import FillRecord, PostTradeState
from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    TOPIC_FILLS,
    TOPIC_HEARTBEAT,
    TOPIC_RAW_TRADES,
    TOPIC_SIGNALS,
    QConsumer,
    QProducer,
)
from quant_core.logging import setup_logging
from quant_core.models import Fill, Signal, Trade, now_ms

logger = logging.getLogger(__name__)

SERVICE_NAME = "post-trade"
DASHBOARD_PORT = 8080


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Post-Trade Analysis Service")

    # --- Shared state ---
    state = PostTradeState()

    # --- Kafka ---
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)
    consumer = QConsumer(
        config.kafka,
        group_id="post-trade",
        topics=[TOPIC_FILLS, TOPIC_RAW_TRADES, TOPIC_SIGNALS],
    )

    # --- FastAPI dashboard ---
    app = create_app(state)

    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(uvicorn_config)

    def run_server():
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info("Dashboard running on http://0.0.0.0:%d", DASHBOARD_PORT)

    # --- Graceful shutdown ---
    shutdown_event = asyncio.Event()

    def handle_signal_os(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()
        server.should_exit = True

    signal.signal(signal.SIGTERM, handle_signal_os)
    signal.signal(signal.SIGINT, handle_signal_os)

    # --- Heartbeat ---
    async def heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            producer.produce(
                topic=TOPIC_HEARTBEAT,
                key=SERVICE_NAME,
                value=f'{{"service":"{SERVICE_NAME}","timestamp":{now_ms()}}}',
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    fill_count = 0
    trade_count = 0
    signal_count = 0

    def consume_loop() -> None:
        nonlocal fill_count, trade_count, signal_count

        while not shutdown_event.is_set():
            msg = consumer.poll(timeout=0.1)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            topic = msg.topic()
            value = msg.value()

            if topic == TOPIC_FILLS:
                try:
                    fill = Fill.from_json(value)
                except Exception:
                    logger.warning("Failed to parse fill")
                    continue

                record = FillRecord(
                    fill_id=fill.fill_id,
                    timestamp=fill.timestamp,
                    symbol=fill.symbol,
                    side=fill.side,
                    quantity=fill.quantity,
                    fill_price=fill.fill_price,
                    fee=fill.fee,
                    slippage_bps=fill.slippage_bps,
                    strategy_id=fill.strategy_id,
                )
                state.process_fill(record)
                fill_count += 1

                if fill_count % 10 == 0:
                    logger.info("Processed %d fills", fill_count)

            elif topic == TOPIC_SIGNALS:
                try:
                    sig = Signal.from_json(value)
                    state.record_signal(
                        signal_id=sig.signal_id,
                        timestamp_ms=sig.timestamp,
                        strategy_id=sig.strategy_id,
                        symbol=sig.symbol,
                        side=sig.side,
                        strength=sig.strength,
                        mid_price=sig.mid_price_at_signal,
                    )
                    signal_count += 1
                    if signal_count % 10 == 0:
                        logger.info("Tracked %d signals for alpha decay", signal_count)
                except Exception:
                    logger.warning("Failed to parse signal")

            elif topic == TOPIC_RAW_TRADES:
                try:
                    trade = Trade.from_json(value)
                    state.update_price(trade.symbol, trade.price, timestamp_ms=trade.timestamp)
                    trade_count += 1
                except Exception:
                    pass

            producer.poll(0.0)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, consume_loop)

    await shutdown_event.wait()

    heartbeat_task.cancel()
    consumer.close()
    producer.flush(timeout=5.0)
    logger.info("Post-Trade stopped. Fills: %d, Trades: %d, Signals: %d", fill_count, trade_count, signal_count)


if __name__ == "__main__":
    asyncio.run(main())
