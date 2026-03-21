"""Market Data Service — entry point.

Connects to exchange WebSocket, normalizes tick data, and publishes
to Kafka topics (raw.trades, raw.depth).
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from quant_core.config import AppConfig
from quant_core.kafka_utils import QProducer, TOPIC_HEARTBEAT
from quant_core.logging import setup_logging
from quant_core.models import now_ms

from market_data_svc.exchange_ws import ExchangeWebSocket
from market_data_svc.normalizer import normalize_message
from market_data_svc.publisher import MarketDataPublisher

logger = logging.getLogger(__name__)

SERVICE_NAME = "market-data"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)

    logger.info(
        "Starting Market Data Service",
        extra={"symbol": ",".join(config.symbols)},
    )

    # Set up Kafka producer
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)
    publisher = MarketDataPublisher(producer)

    # Message handler: normalize and publish
    async def on_message(raw: dict) -> None:
        event = normalize_message(raw)
        if event is not None:
            publisher.publish(event)

    # Set up WebSocket connection
    ws = ExchangeWebSocket(symbols=config.symbols, on_message=on_message)

    # Heartbeat task
    async def heartbeat_loop() -> None:
        while True:
            producer.produce(
                topic=TOPIC_HEARTBEAT,
                key=SERVICE_NAME,
                value=f'{{"service":"{SERVICE_NAME}","timestamp":{now_ms()}}}',
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run WebSocket + heartbeat concurrently
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    ws_task = asyncio.create_task(ws.start())

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cleanup
    logger.info("Shutting down Market Data Service...")
    await ws.stop()
    heartbeat_task.cancel()
    ws_task.cancel()
    publisher.flush()

    logger.info(
        "Market Data Service stopped. Stats: %s",
        publisher.stats,
    )


if __name__ == "__main__":
    asyncio.run(main())
