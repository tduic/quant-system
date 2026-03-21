"""Post-Trade Analysis Service — entry point.

Consumes fills + market data, computes analytics, serves the dashboard
via FastAPI, and provides Excel export.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from quant_core.config import AppConfig
from quant_core.logging import setup_logging

logger = logging.getLogger(__name__)

SERVICE_NAME = "post-trade"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Post-Trade Analysis Service")

    # TODO: Phase 4
    # 1. Subscribe to fills topic
    # 2. Compute real-time PnL (realized + unrealized)
    # 3. Run TCA on each fill (slippage decomposition)
    # 4. Compute rolling risk metrics (Sharpe, Sortino, Calmar)
    # 5. Serve FastAPI dashboard on :8080
    # 6. Excel export endpoint

    shutdown_event = asyncio.Event()

    def handle_signal(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await shutdown_event.wait()
    logger.info("Post-Trade Analysis Service stopped")


if __name__ == "__main__":
    asyncio.run(main())
