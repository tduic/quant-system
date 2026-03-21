"""Risk Gateway Service — entry point.

Sits between the Alpha Engine and Execution Service. Consumes signals,
applies risk checks (position limits, drawdown, exposure), and publishes
approved orders or rejection events.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from quant_core.config import AppConfig
from quant_core.logging import setup_logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "risk-gateway"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Risk Gateway Service")

    # TODO: Phase 2
    # 1. Load risk parameters from config/Redis
    # 2. Subscribe to signals topic
    # 3. For each signal, run risk checks pipeline
    # 4. Publish approved orders to orders topic, or rejections to risk.decisions

    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await shutdown_event.wait()
    logger.info("Risk Gateway Service stopped")


if __name__ == "__main__":
    asyncio.run(main())
