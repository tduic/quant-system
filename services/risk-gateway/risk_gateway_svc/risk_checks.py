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

    max_position_notional: float = 10_000.0  # max notional per symbol in USD
    max_order_notional: float = 1_000.0  # max single order value in USD
    max_drawdown_pct: float = 0.10  # 10% hard stop drawdown
    max_total_exposure: float = 500_000.0  # max total notional exposure
    max_var_pct: float = 0.02  # max VaR as % of equity (2%)


def check_position_notional(signal: Signal, state: PortfolioState, limits: RiskLimits) -> str | None:
    """Check that resulting position notional doesn't exceed per-symbol limit.

    Uses the signal's mid_price to convert quantity to USD notional. This works
    correctly across assets with wildly different unit prices (BTC ~$75K vs SOL ~$88).
    """
    current_pos = state.positions.get(signal.symbol, 0.0)
    new_pos = current_pos + signal.target_quantity
    price = signal.mid_price_at_signal
    new_notional = abs(new_pos) * price if price > 0 else 0.0
    if new_notional > limits.max_position_notional:
        return (
            f"position_notional: resulting ${new_notional:,.0f} "
            f"({new_pos:.6f} @ ${price:,.0f}) exceeds limit ${limits.max_position_notional:,.0f}"
        )
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


def drawdown_scale_factor(state: PortfolioState, limits: RiskLimits) -> float:
    """Graduated position scaling based on drawdown severity.

    Returns a multiplier (0.0 to 1.0) applied to order quantity:
        - 0-3% drawdown: full size (1.0)
        - 3-7% drawdown: linearly scale from 1.0 to 0.25
        - 7-10% drawdown: 0.25x (minimal size, stay in the game)
        - >10% drawdown: 0.0 (hard stop via check_drawdown)
    """
    if state.peak_equity <= 0:
        return 1.0
    drawdown = (state.peak_equity - state.current_equity) / state.peak_equity
    if drawdown <= 0.03:
        return 1.0
    if drawdown <= 0.07:
        # Linear scale from 1.0 at 3% to 0.25 at 7%
        return 1.0 - (drawdown - 0.03) / 0.04 * 0.75
    return 0.25


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


def check_total_exposure(
    signal: Signal,
    state: PortfolioState,
    limits: RiskLimits,
    latest_prices: dict[str, float] | None = None,
) -> str | None:
    """Check that total portfolio exposure across all symbols stays within limits.

    Total exposure = sum of abs(position * price) for all symbols.
    """
    prices = latest_prices or {}
    total_exposure = 0.0
    for sym, qty in state.positions.items():
        price = prices.get(sym, 0.0)
        total_exposure += abs(qty * price)

    # Add the proposed order's notional
    proposed_notional = signal.target_quantity * signal.mid_price_at_signal
    new_exposure = total_exposure + proposed_notional

    if new_exposure > limits.max_total_exposure:
        return f"total_exposure: projected {new_exposure:.2f} exceeds limit {limits.max_total_exposure:.2f}"
    return None


def run_risk_checks(
    signal: Signal,
    state: PortfolioState,
    limits: RiskLimits,
    var_pct: float | None = None,
    latest_prices: dict[str, float] | None = None,
) -> RiskDecision:
    """Run all risk checks and return a decision."""
    checks_passed = []
    checks_failed = []

    # Run each check
    for check_name, result in [
        ("position_notional", check_position_notional(signal, state, limits)),
        ("order_notional", check_order_notional(signal, limits)),
        ("drawdown", check_drawdown(state, limits)),
        ("var", check_var(state, limits, var_pct)),
        ("total_exposure", check_total_exposure(signal, state, limits, latest_prices)),
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

    # Apply graduated position scaling based on drawdown
    scale = drawdown_scale_factor(state, limits)
    adjusted_qty = signal.target_quantity * scale

    return RiskDecision(
        signal_id=signal.signal_id,
        decision="APPROVED",
        reason="all_checks_passed" if scale >= 1.0 else f"scaled_by_drawdown({scale:.2f})",
        adjusted_quantity=adjusted_qty,
        timestamp=now_ms(),
        checks_passed=checks_passed,
        checks_failed=[],
    )
