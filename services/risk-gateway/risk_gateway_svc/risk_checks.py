"""Risk check pipeline.

Each check is a function that takes a Signal + current portfolio state
and returns a RiskDecision. Checks are composable and run in sequence.

Phase 2 checks (simple):
    - max_position_size: reject if resulting position exceeds limit
    - max_drawdown: reject if current drawdown exceeds threshold
    - max_order_value: reject if notional order value too large

Phase 3 additions (quantitative):
    - parametric_var: VaR using GBM volatility model
    - correlation_check: reject if adding correlated exposure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant_core.models import RiskDecision, Signal, now_ms

logger = logging.getLogger(__name__)


@dataclass
class PortfolioState:
    """Current portfolio state from Redis."""

    positions: dict[str, float]  # symbol -> signed quantity
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0


@dataclass
class RiskLimits:
    """Configurable risk parameters."""

    max_position_size: float = 1.0  # max quantity per symbol
    max_order_notional: float = 100_000.0  # max single order value in USD
    max_drawdown_pct: float = 0.05  # 5% max drawdown
    max_total_exposure: float = 500_000.0  # max total notional exposure
    max_var_pct: float = 0.02  # max VaR as % of equity (2%)


def check_position_size(signal: Signal, state: PortfolioState, limits: RiskLimits) -> str | None:
    """Returns failure reason, or None if check passes."""
    current_pos = state.positions.get(signal.symbol, 0.0)
    new_pos = current_pos + signal.target_quantity
    if abs(new_pos) > limits.max_position_size:
        return f"position_size: resulting position {new_pos:.6f} exceeds limit {limits.max_position_size}"
    return None


def check_order_notional(signal: Signal, limits: RiskLimits) -> str | None:
    """Check that single order notional doesn't exceed limit."""
    notional = signal.target_quantity * signal.mid_price_at_signal
    if notional > limits.max_order_notional:
        return f"order_notional: {notional:.2f} exceeds limit {limits.max_order_notional:.2f}"
    return None


def check_drawdown(state: PortfolioState, limits: RiskLimits) -> str | None:
    """Check that current drawdown is within limits."""
    if state.peak_equity <= 0:
        return None
    drawdown = (state.peak_equity - state.current_equity) / state.peak_equity
    if drawdown > limits.max_drawdown_pct:
        return f"drawdown: current {drawdown:.2%} exceeds limit {limits.max_drawdown_pct:.2%}"
    return None


def check_var(state: PortfolioState, limits: RiskLimits, var_pct: float | None = None) -> str | None:
    """Check that estimated VaR is within limits.

    var_pct is provided by the ParametricVaR model externally.
    If not provided, the check passes (graceful degradation).
    """
    if var_pct is None:
        return None  # no VaR estimate available, pass
    if var_pct > limits.max_var_pct:
        return f"var: estimated {var_pct:.2%} exceeds limit {limits.max_var_pct:.2%}"
    return None


def run_risk_checks(
    signal: Signal,
    state: PortfolioState,
    limits: RiskLimits,
    var_pct: float | None = None,
) -> RiskDecision:
    """Run all risk checks and return a decision."""
    checks_passed = []
    checks_failed = []

    # Run each check
    for check_name, result in [
        ("position_size", check_position_size(signal, state, limits)),
        ("order_notional", check_order_notional(signal, limits)),
        ("drawdown", check_drawdown(state, limits)),
        ("var", check_var(state, limits, var_pct)),
    ]:
        if result is None:
            checks_passed.append(check_name)
        else:
            checks_failed.append(check_name)
            logger.warning("Risk check failed: %s", result)

    if checks_failed:
        return RiskDecision(
            signal_id=signal.signal_id,
            decision="REJECTED",
            reason="; ".join(checks_failed),
            adjusted_quantity=0.0,
            timestamp=now_ms(),
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    return RiskDecision(
        signal_id=signal.signal_id,
        decision="APPROVED",
        reason="all_checks_passed",
        adjusted_quantity=signal.target_quantity,
        timestamp=now_ms(),
        checks_passed=checks_passed,
        checks_failed=[],
    )
