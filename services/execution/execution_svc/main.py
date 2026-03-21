"""Execution Service — entry point.

Receives approved orders from the Risk Gateway, manages the order lifecycle
(paper trading or live), and publishes fill events.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from quant_core.config import AppConfig
from quant_core.logging import setup_logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "execution"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Execution Service")

    # TODO: Phase 2
    # 1. Subscribe to orders topic
    # 2. For each order, simulate fill using current market data
    # 3. Compute slippage against mid price at signal time
    # 4. Publish Fill events to fills topic
    # 5. Update position state in Redis

    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await shutdown_event.wait()
    logger.info("Execution Service stopped")


if __name__ == "__main__":
    asyncio.run(main())
