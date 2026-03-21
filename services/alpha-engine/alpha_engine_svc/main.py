"""Alpha Engine Service — entry point.

Consumes market data from Kafka/Redis, computes signals via pluggable
strategies, and publishes trade recommendations to the signals topic.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from quant_core.config import AppConfig
from quant_core.logging import setup_logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "alpha-engine"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Alpha Engine Service")

    # TODO: Phase 2
    # 1. Initialize strategy registry
    # 2. Subscribe to raw.trades + raw.depth via Kafka
    # 3. Maintain in-memory order book from depth updates
    # 4. Feed trades/book state to active strategies
    # 5. Publish Signal events to signals topic

    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await shutdown_event.wait()
    logger.info("Alpha Engine Service stopped")


if __name__ == "__main__":
    asyncio.run(main())
