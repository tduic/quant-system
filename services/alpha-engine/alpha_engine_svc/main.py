"""Alpha Engine Service — entry point.

Consumes market data from Kafka, maintains order books, computes features
via pluggable strategies, and publishes trade signals.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from alpha_engine_svc.order_book import OrderBook
from alpha_engine_svc.strategies.mean_reversion import MeanReversionStrategy
from alpha_engine_svc.strategy import StrategyRegistry
from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    TOPIC_HEARTBEAT,
    TOPIC_RAW_DEPTH,
    TOPIC_RAW_TRADES,
    TOPIC_SIGNALS,
    QConsumer,
    QProducer,
)
from quant_core.logging import setup_logging
from quant_core.models import DepthUpdate, Trade, now_ms

logger = logging.getLogger(__name__)

SERVICE_NAME = "alpha-engine"


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)

    logger.info(
        "Starting Alpha Engine Service",
        extra={"symbols": ",".join(config.symbols)},
    )

    # --- Kafka ---
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)
    consumer = QConsumer(
        config.kafka,
        group_id="alpha-engine",
        topics=[TOPIC_RAW_TRADES, TOPIC_RAW_DEPTH],
    )

    # --- Order books (one per symbol) ---
    books: dict[str, OrderBook] = {}
    for sym in config.symbols:
        books[sym.upper()] = OrderBook(symbol=sym.upper())

    # --- Strategy registry ---
    registry = StrategyRegistry()
    for sym in config.symbols:
        strategy = MeanReversionStrategy(
            strategy_id=f"mean_reversion_{sym}",
            symbol=sym.upper(),
        )
        registry.register(strategy)

    # --- Counters ---
    trade_count = 0
    signal_count = 0

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
                value=f'{{"service":"{SERVICE_NAME}","timestamp":{now_ms()},"trades":{trade_count},"signals":{signal_count}}}',
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    def consume_loop() -> None:
        nonlocal trade_count, signal_count

        while not shutdown_event.is_set():
            msg = consumer.poll(timeout=0.1)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            topic = msg.topic()
            try:
                value = msg.value()
            except Exception:
                continue

            if topic == TOPIC_RAW_TRADES:
                trade = Trade.from_json(value)
                symbol = trade.symbol.upper()
                trade_count += 1

                for strat in registry.strategies_for_symbol(symbol):
                    sig = strat.on_trade(trade)
                    if sig is not None:
                        producer.produce(
                            topic=TOPIC_SIGNALS,
                            key=sig.symbol,
                            value=sig.to_json(),
                        )
                        signal_count += 1
                        logger.info(
                            "Signal emitted: %s %s %s (z=%.2f)",
                            sig.side,
                            sig.symbol,
                            sig.strategy_id,
                            sig.metadata.get("z_score", 0),
                        )

            elif topic == TOPIC_RAW_DEPTH:
                depth = DepthUpdate.from_json(value)
                symbol = depth.symbol.upper()

                if symbol in books:
                    books[symbol].apply_delta(depth)

                for strat in registry.strategies_for_symbol(symbol):
                    strat.on_book_update(depth)

            producer.poll(0.0)

            if trade_count > 0 and trade_count % 5000 == 0:
                logger.info("Processed %d trades, emitted %d signals", trade_count, signal_count)

    # Run blocking consume in a thread
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, consume_loop)

    await shutdown_event.wait()

    # Cleanup
    heartbeat_task.cancel()
    consumer.close()
    producer.flush(timeout=5.0)
    logger.info("Alpha Engine stopped. Trades: %d, Signals: %d", trade_count, signal_count)


if __name__ == "__main__":
    asyncio.run(main())
