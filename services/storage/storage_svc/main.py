"""Storage Service — entry point.

Consumes market data events from Kafka (raw.trades, raw.depth) and
persists them to TimescaleDB using batched writes for throughput.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import asyncpg

from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    QConsumer,
    TOPIC_RAW_TRADES,
    TOPIC_RAW_DEPTH,
    TOPIC_FILLS,
)
from quant_core.logging import setup_logging

from storage_svc.batch_writer import BatchWriter
from storage_svc.consumer import StorageConsumer

logger = logging.getLogger(__name__)

SERVICE_NAME = "storage"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)

    logger.info("Starting Storage Service")

    # Database connection pool
    pool = await asyncpg.create_pool(
        dsn=config.database.url,
        min_size=config.database.min_pool_size,
        max_size=config.database.max_pool_size,
    )
    logger.info("Database pool created")

    # Kafka consumer
    batch_size = int(os.getenv("BATCH_SIZE", "1000"))
    batch_timeout = int(os.getenv("BATCH_TIMEOUT_MS", "1000"))

    kafka_consumer = QConsumer(
        config=config.kafka,
        group_id=SERVICE_NAME,
        topics=[TOPIC_RAW_TRADES, TOPIC_RAW_DEPTH],
    )

    writer = BatchWriter(
        pool=pool,
        batch_size=batch_size,
        batch_timeout_ms=batch_timeout,
    )
    consumer = StorageConsumer(kafka_consumer, writer)

    # Graceful shutdown
    running = True

    def handle_signal(sig: int, frame) -> None:
        nonlocal running
        logger.info("Received signal %s, shutting down...", sig)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Main consume loop
    logger.info(
        "Storage service ready — consuming from [%s, %s] with batch_size=%d, timeout=%dms",
        TOPIC_RAW_TRADES,
        TOPIC_RAW_DEPTH,
        batch_size,
        batch_timeout,
    )

    try:
        while running:
            # Process available messages
            count = consumer.process_batch()

            # Flush if buffer is full or timed out
            if writer.should_flush:
                await writer.flush()

            # Small sleep to prevent tight-looping when no messages
            if count == 0:
                await asyncio.sleep(0.01)

    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        # Final flush
        logger.info("Final flush...")
        await writer.flush()
        kafka_consumer.close()
        await pool.close()
        logger.info("Storage Service stopped. Stats: %s", writer.stats)


if __name__ == "__main__":
    asyncio.run(main())
