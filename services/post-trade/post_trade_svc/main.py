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
from quant_core.metrics import MetricsRegistry
from quant_core.models import Fill, Signal, Trade, now_ms
from quant_core.portfolio_state import sync_portfolio_to_redis
from quant_core.redis_utils import create_sync_redis

logger = logging.getLogger(__name__)

SERVICE_NAME = "post-trade"
DASHBOARD_PORT = 8080


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Post-Trade Analysis Service")

    # --- Metrics ---
    metrics = MetricsRegistry(SERVICE_NAME)
    metrics.start_http_server(port=9090)

    # --- Shared state ---
    state = PostTradeState()
    run_id = config.backtest_id or "live"

    # --- Redis (for portfolio state sync) ---
    redis_client = create_sync_redis(config.redis)

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
                    trading_mode=fill.trading_mode,
                )
                state.process_fill(record)
                fill_count += 1
                metrics.inc("fills_processed", labels={"symbol": fill.symbol})
                metrics.set_gauge("portfolio_equity", state._peak_equity)  # Updated below with real value

                # Sync portfolio state to Redis for the risk gateway
                try:
                    pnl_data = state.get_pnl_summary()
                    positions_for_redis = {}
                    for sym, pos in pnl_data.get("positions", {}).items():
                        positions_for_redis[sym] = {
                            "quantity": pos["quantity"],
                            "avg_entry_price": pos["avg_entry_price"],
                            "realized_pnl": pos["realized_pnl"],
                            "unrealized_pnl": pos["unrealized_pnl"],
                        }
                    sync_portfolio_to_redis(
                        r=redis_client,
                        run_id=run_id,
                        positions=positions_for_redis,
                        current_equity=pnl_data["current_equity"],
                        peak_equity=state._peak_equity,
                        realized_pnl=pnl_data["total_realized_pnl"],
                        unrealized_pnl=pnl_data["total_unrealized_pnl"],
                        total_fees=pnl_data["total_fees"],
                    )
                    # Update portfolio metrics
                    metrics.set_gauge("portfolio_equity", pnl_data["current_equity"])
                    metrics.set_gauge("portfolio_peak_equity", state._peak_equity)
                    metrics.set_gauge("portfolio_realized_pnl", pnl_data["total_realized_pnl"])
                    metrics.set_gauge("portfolio_unrealized_pnl", pnl_data["total_unrealized_pnl"])
                    metrics.set_gauge("portfolio_total_fees", pnl_data["total_fees"])
                    drawdown = (
                        1.0 - (pnl_data["current_equity"] / state._peak_equity) if state._peak_equity > 0 else 0.0
                    )
                    metrics.set_gauge("portfolio_drawdown_pct", drawdown)
                except Exception:
                    logger.warning("Failed to sync portfolio state to Redis")

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
                    metrics.inc("trades_processed", labels={"symbol": trade.symbol})
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
