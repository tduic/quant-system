"""Risk Gateway Service — entry point.

Sits between the Alpha Engine and Execution Service. Consumes signals,
applies risk checks (position limits, drawdown, exposure), and publishes
approved orders or rejection events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    QConsumer,
    QProducer,
    TOPIC_SIGNALS,
    TOPIC_ORDERS,
    TOPIC_RISK_EVENTS,
    TOPIC_HEARTBEAT,
)
from quant_core.logging import setup_logging
from quant_core.models import Signal, Order, now_ms
from quant_core.redis_utils import Keys

from risk_gateway_svc.risk_checks import (
    PortfolioState,
    RiskLimits,
    run_risk_checks,
)

logger = logging.getLogger(__name__)

SERVICE_NAME = "risk-gateway"


def _load_risk_limits() -> RiskLimits:
    """Load risk limits from environment variables."""
    return RiskLimits(
        max_position_size=float(os.getenv("MAX_POSITION_SIZE", "1.0")),
        max_order_notional=float(os.getenv("MAX_ORDER_NOTIONAL", "100000")),
        max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "0.05")),
        max_total_exposure=float(os.getenv("MAX_TOTAL_EXPOSURE", "500000")),
    )


def _get_portfolio_state() -> PortfolioState:
    """Get current portfolio state. In Phase 2, reads from Redis.
    For now, returns a flat state (no positions).
    """
    # TODO: read positions, equity, peak from Redis
    return PortfolioState(
        positions={},
        peak_equity=100_000.0,
        current_equity=100_000.0,
    )


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Risk Gateway Service")

    # --- Config ---
    limits = _load_risk_limits()
    logger.info(
        "Risk limits: pos=%.2f, notional=%.0f, drawdown=%.1f%%",
        limits.max_position_size, limits.max_order_notional,
        limits.max_drawdown_pct * 100,
    )

    # --- Kafka ---
    producer = QProducer(config.kafka, backtest_id=config.backtest_id)
    consumer = QConsumer(
        config.kafka,
        group_id="risk-gateway",
        topics=[TOPIC_SIGNALS],
    )

    # --- Counters ---
    approved_count = 0
    rejected_count = 0

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
                value=f'{{"service":"{SERVICE_NAME}","timestamp":{now_ms()},"approved":{approved_count},"rejected":{rejected_count}}}',
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    def consume_loop() -> None:
        nonlocal approved_count, rejected_count

        while not shutdown_event.is_set():
            msg = consumer.poll(timeout=0.1)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            try:
                sig = Signal.from_json(msg.value())
            except Exception:
                logger.warning("Failed to parse signal")
                continue

            # Get current portfolio state
            state = _get_portfolio_state()

            # Run risk checks
            decision = run_risk_checks(sig, state, limits)

            # Publish decision
            producer.produce(
                topic=TOPIC_RISK_EVENTS,
                key=sig.symbol,
                value=decision.to_json(),
            )

            if decision.decision == "APPROVED":
                approved_count += 1
                # Create order from signal
                order = Order(
                    timestamp=now_ms(),
                    symbol=sig.symbol,
                    side=sig.side,
                    order_type="MARKET",
                    quantity=decision.adjusted_quantity,
                    signal_id=sig.signal_id,
                    strategy_id=sig.strategy_id,
                    backtest_id=config.backtest_id,
                )
                producer.produce(
                    topic=TOPIC_ORDERS,
                    key=order.symbol,
                    value=order.to_json(),
                )
                logger.info(
                    "APPROVED: %s %s %.6f %s",
                    order.side, order.symbol, order.quantity, order.strategy_id,
                )
            else:
                rejected_count += 1
                logger.info(
                    "REJECTED: %s %s — %s",
                    sig.side, sig.symbol, decision.reason,
                )

            producer.poll(0.0)

    loop = asyncio.get_event_loop()
    consume_task = loop.run_in_executor(None, consume_loop)

    await shutdown_event.wait()

    heartbeat_task.cancel()
    consumer.close()
    producer.flush(timeout=5.0)
    logger.info("Risk Gateway stopped. Approved: %d, Rejected: %d", approved_count, rejected_count)


if __name__ == "__main__":
    asyncio.run(main())
