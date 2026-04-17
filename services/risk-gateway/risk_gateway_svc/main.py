"""Risk Gateway Service — entry point.

Sits between the Alpha Engine and Execution Service. Consumes signals,
applies risk checks (position limits, drawdown, exposure), and publishes
approved orders or rejection events.

Includes circuit breaker integration: when tripped, all signals are
rejected immediately without running checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

from quant_core.circuit_breaker import CircuitBreaker
from quant_core.config import AppConfig
from quant_core.kafka_utils import (
    TOPIC_AUDIT,
    TOPIC_HEARTBEAT,
    TOPIC_ORDERS,
    TOPIC_RISK_EVENTS,
    TOPIC_SIGNALS,
    QConsumer,
    QProducer,
)
from quant_core.logging import setup_logging
from quant_core.metrics import MetricsRegistry
from quant_core.models import Order, RiskDecision, Signal, now_ms
from quant_core.portfolio_state import read_portfolio_from_redis
from quant_core.redis_utils import create_sync_redis
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


def _get_portfolio_state(redis_client, run_id: str) -> PortfolioState:
    """Get current portfolio state from Redis.

    The post-trade service writes portfolio state to Redis after every
    fill. We read it here for real-time risk checks.
    """
    data = read_portfolio_from_redis(redis_client, run_id)
    return PortfolioState(
        positions=data["positions"],
        peak_equity=data["peak_equity"],
        current_equity=data["current_equity"],
        realized_pnl=data.get("realized_pnl", 0.0),
        unrealized_pnl=data.get("unrealized_pnl", 0.0),
    )


def _emit_audit(
    producer: QProducer,
    event_type: str,
    detail: dict,
) -> None:
    """Publish an audit event to the audit log topic."""
    producer.produce(
        topic=TOPIC_AUDIT,
        key=SERVICE_NAME,
        value=json.dumps(
            {
                "service": SERVICE_NAME,
                "event": event_type,
                "timestamp": now_ms(),
                **detail,
            }
        ),
    )


async def main() -> None:
    config = AppConfig.from_env()
    setup_logging(SERVICE_NAME, level=config.log_level)
    logger.info("Starting Risk Gateway Service")

    run_id = config.backtest_id or "live"

    # --- Metrics ---
    metrics = MetricsRegistry(SERVICE_NAME)
    metrics.start_http_server(port=9090)

    # --- Redis ---
    redis_client = create_sync_redis(config.redis)

    # --- Circuit breaker ---
    cb = CircuitBreaker(redis_client, run_id=run_id)
    logger.info("Circuit breaker initialized (run_id=%s)", run_id)

    # --- Config ---
    limits = _load_risk_limits()
    logger.info(
        "Risk limits: pos=%.2f, notional=%.0f, drawdown=%.1f%%",
        limits.max_position_size,
        limits.max_order_notional,
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
    breaker_blocked = 0

    # --- Graceful shutdown ---
    shutdown_event = asyncio.Event()

    def handle_signal_os(sig: int, frame) -> None:
        logger.info("Received signal %s, shutting down...", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal_os)
    signal.signal(signal.SIGINT, handle_signal_os)

    # --- Kill switch HTTP endpoint ---
    import threading

    import uvicorn
    from fastapi import FastAPI

    kill_app = FastAPI(title="Risk Gateway Controls")

    @kill_app.get("/api/circuit-breaker")
    def breaker_status():
        return cb.status()

    @kill_app.post("/api/circuit-breaker/trip")
    def trip_breaker(reason: str = "manual", triggered_by: str = "api"):
        cb.trip(reason=reason, triggered_by=triggered_by)
        _emit_audit(producer, "circuit_breaker_tripped", {"reason": reason, "triggered_by": triggered_by})
        return {"status": "tripped", "reason": reason}

    @kill_app.post("/api/circuit-breaker/reset")
    def reset_breaker(reset_by: str = "api"):
        cb.reset(reset_by=reset_by)
        _emit_audit(producer, "circuit_breaker_reset", {"reset_by": reset_by})
        return {"status": "reset"}

    @kill_app.get("/health")
    def health():
        return {
            "status": "ok",
            "approved": approved_count,
            "rejected": rejected_count,
            "breaker_blocked": breaker_blocked,
        }

    kill_port = int(os.getenv("RISK_API_PORT", "8090"))
    uvicorn_config = uvicorn.Config(kill_app, host="0.0.0.0", port=kill_port, log_level="warning")
    kill_server = uvicorn.Server(uvicorn_config)
    threading.Thread(target=kill_server.run, daemon=True).start()
    logger.info("Kill switch API on http://0.0.0.0:%d", kill_port)

    # --- Heartbeat ---
    async def heartbeat_loop() -> None:
        while not shutdown_event.is_set():
            producer.produce(
                topic=TOPIC_HEARTBEAT,
                key=SERVICE_NAME,
                value=json.dumps(
                    {
                        "service": SERVICE_NAME,
                        "timestamp": now_ms(),
                        "approved": approved_count,
                        "rejected": rejected_count,
                        "breaker_blocked": breaker_blocked,
                        "breaker_tripped": cb.is_tripped(),
                    }
                ),
            )
            producer.poll(0.0)
            await asyncio.sleep(10)

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    # --- Main consume loop ---
    def consume_loop() -> None:
        nonlocal approved_count, rejected_count, breaker_blocked

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

            # --- Circuit breaker check ---
            if cb.is_tripped():
                breaker_blocked += 1
                metrics.inc("signals_breaker_blocked", labels={"symbol": sig.symbol})
                metrics.set_gauge("circuit_breaker_active", 1.0)
                decision = RiskDecision(
                    signal_id=sig.signal_id,
                    decision="REJECTED",
                    reason="circuit_breaker_tripped",
                    adjusted_quantity=0.0,
                    timestamp=now_ms(),
                    checks_passed=[],
                    checks_failed=["circuit_breaker"],
                )
                producer.produce(
                    topic=TOPIC_RISK_EVENTS,
                    key=sig.symbol,
                    value=decision.to_json(),
                )
                if breaker_blocked % 100 == 1:
                    logger.warning("Circuit breaker active — blocked %d signals", breaker_blocked)
                producer.poll(0.0)
                continue

            # Get current portfolio state from Redis
            state = _get_portfolio_state(redis_client, run_id)

            # Run risk checks
            decision = run_risk_checks(sig, state, limits)

            # Publish decision
            producer.produce(
                topic=TOPIC_RISK_EVENTS,
                key=sig.symbol,
                value=decision.to_json(),
            )

            metrics.set_gauge("circuit_breaker_active", 0.0)

            if decision.decision == "APPROVED":
                approved_count += 1
                metrics.inc("orders_approved", labels={"symbol": sig.symbol})
                metrics.set_gauge("portfolio_equity", state.current_equity)
                metrics.set_gauge(
                    "portfolio_drawdown",
                    1.0 - (state.current_equity / state.peak_equity) if state.peak_equity > 0 else 0.0,
                )
                # Choose order type based on signal urgency:
                #   urgency >= 0.8 → MARKET (taker, higher fees, immediate fill)
                #   urgency <  0.8 → LIMIT  (maker, lower fees, may not fill)
                if sig.urgency >= 0.8:
                    order_type = "MARKET"
                    limit_price = None
                else:
                    order_type = "LIMIT"
                    # Place limit at the current mid price (aggressive limit)
                    limit_price = sig.mid_price_at_signal

                order = Order(
                    timestamp=now_ms(),
                    symbol=sig.symbol,
                    side=sig.side,
                    order_type=order_type,
                    quantity=decision.adjusted_quantity,
                    limit_price=limit_price,
                    signal_id=sig.signal_id,
                    strategy_id=sig.strategy_id,
                    backtest_id=config.backtest_id,
                )
                producer.produce(
                    topic=TOPIC_ORDERS,
                    key=order.symbol,
                    value=order.to_json(),
                )
                _emit_audit(
                    producer,
                    "order_approved",
                    {
                        "order_id": order.order_id,
                        "signal_id": sig.signal_id,
                        "symbol": order.symbol,
                        "side": order.side,
                        "quantity": order.quantity,
                    },
                )
                logger.info(
                    "APPROVED: %s %s %.6f %s [%s, urgency=%.2f]",
                    order.side,
                    order.symbol,
                    order.quantity,
                    order.strategy_id,
                    order.order_type,
                    sig.urgency,
                )
            else:
                rejected_count += 1
                metrics.inc("orders_rejected", labels={"symbol": sig.symbol, "reason": decision.reason})
                _emit_audit(
                    producer,
                    "order_rejected",
                    {
                        "signal_id": sig.signal_id,
                        "symbol": sig.symbol,
                        "side": sig.side,
                        "reason": decision.reason,
                    },
                )
                logger.info(
                    "REJECTED: %s %s — %s",
                    sig.side,
                    sig.symbol,
                    decision.reason,
                )

            producer.poll(0.0)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, consume_loop)

    await shutdown_event.wait()

    heartbeat_task.cancel()
    kill_server.should_exit = True
    consumer.close()
    producer.flush(timeout=5.0)
    logger.info(
        "Risk Gateway stopped. Approved: %d, Rejected: %d, Breaker-blocked: %d",
        approved_count,
        rejected_count,
        breaker_blocked,
    )


if __name__ == "__main__":
    asyncio.run(main())
