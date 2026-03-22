"""Tests for risk_gateway_svc.risk_checks — risk check pipeline."""

from __future__ import annotations

import pytest

from quant_core.models import Signal
from risk_gateway_svc.risk_checks import (
    PortfolioState,
    RiskLimits,
    check_drawdown,
    check_order_notional,
    check_position_size,
    check_var,
    run_risk_checks,
)


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits(
        max_position_size=1.0,
        max_order_notional=100_000.0,
        max_drawdown_pct=0.05,
    )


@pytest.fixture
def flat_state() -> PortfolioState:
    return PortfolioState(
        positions={},
        peak_equity=100_000.0,
        current_equity=100_000.0,
    )


@pytest.fixture
def signal() -> Signal:
    return Signal(
        strategy_id="test",
        symbol="BTCUSD",
        side="BUY",
        strength=0.8,
        target_quantity=0.5,
        mid_price_at_signal=80_000.0,
        spread_at_signal=1.0,
    )


class TestCheckPositionSize:
    def test_within_limit_passes(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        assert check_position_size(signal, flat_state, limits) is None

    def test_exceeds_limit_fails(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        signal.target_quantity = 1.5  # exceeds max_position_size=1.0
        result = check_position_size(signal, flat_state, limits)
        assert result is not None
        assert "position_size" in result

    def test_existing_position_considered(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        flat_state.positions["BTCUSD"] = 0.8
        signal.target_quantity = 0.3  # 0.8 + 0.3 = 1.1 > 1.0
        result = check_position_size(signal, flat_state, limits)
        assert result is not None

    def test_reducing_position_passes(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        flat_state.positions["BTCUSD"] = 0.8
        signal.target_quantity = -0.3  # 0.8 - 0.3 = 0.5, within limit
        result = check_position_size(signal, flat_state, limits)
        assert result is None


class TestCheckOrderNotional:
    def test_within_limit_passes(self, signal: Signal, limits: RiskLimits):
        # 0.5 * 80000 = 40000 < 100000
        assert check_order_notional(signal, limits) is None

    def test_exceeds_limit_fails(self, signal: Signal, limits: RiskLimits):
        signal.target_quantity = 2.0  # 2.0 * 80000 = 160000 > 100000
        result = check_order_notional(signal, limits)
        assert result is not None
        assert "order_notional" in result


class TestCheckDrawdown:
    def test_no_drawdown_passes(self, flat_state: PortfolioState, limits: RiskLimits):
        assert check_drawdown(flat_state, limits) is None

    def test_within_drawdown_limit_passes(self, flat_state: PortfolioState, limits: RiskLimits):
        flat_state.current_equity = 96_000.0  # 4% drawdown < 5%
        assert check_drawdown(flat_state, limits) is None

    def test_exceeds_drawdown_limit_fails(self, flat_state: PortfolioState, limits: RiskLimits):
        flat_state.current_equity = 94_000.0  # 6% drawdown > 5%
        result = check_drawdown(flat_state, limits)
        assert result is not None
        assert "drawdown" in result

    def test_zero_peak_equity_passes(self, flat_state: PortfolioState, limits: RiskLimits):
        flat_state.peak_equity = 0.0
        assert check_drawdown(flat_state, limits) is None


class TestRunRiskChecks:
    def test_all_pass_approved(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits)
        assert decision.decision == "APPROVED"
        assert len(decision.checks_passed) == 4  # position, notional, drawdown, var
        assert len(decision.checks_failed) == 0
        assert decision.adjusted_quantity == signal.target_quantity

    def test_one_fails_rejected(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        signal.target_quantity = 2.0  # fails notional check
        decision = run_risk_checks(signal, flat_state, limits)
        assert decision.decision == "REJECTED"
        assert "order_notional" in decision.checks_failed
        assert decision.adjusted_quantity == 0.0

    def test_multiple_fail_all_reported(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        signal.target_quantity = 2.0  # fails position_size AND notional
        flat_state.current_equity = 90_000.0  # also fails drawdown
        decision = run_risk_checks(signal, flat_state, limits)
        assert decision.decision == "REJECTED"
        assert len(decision.checks_failed) >= 2

    def test_signal_id_propagated(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits)
        assert decision.signal_id == signal.signal_id

    def test_timestamp_set(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits)
        assert decision.timestamp > 0

    def test_var_check_rejects_when_exceeded(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits, var_pct=0.10)
        assert decision.decision == "REJECTED"
        assert "var" in decision.checks_failed

    def test_var_check_passes_when_within_limit(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits, var_pct=0.01)
        assert decision.decision == "APPROVED"
        assert "var" in decision.checks_passed

    def test_var_check_passes_when_none(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        decision = run_risk_checks(signal, flat_state, limits, var_pct=None)
        assert decision.decision == "APPROVED"
        assert "var" in decision.checks_passed


class TestCheckVar:
    def test_none_var_passes(self, flat_state: PortfolioState, limits: RiskLimits):
        assert check_var(flat_state, limits, var_pct=None) is None

    def test_within_limit_passes(self, flat_state: PortfolioState, limits: RiskLimits):
        assert check_var(flat_state, limits, var_pct=0.01) is None

    def test_exceeds_limit_fails(self, flat_state: PortfolioState, limits: RiskLimits):
        result = check_var(flat_state, limits, var_pct=0.05)
        assert result is not None
        assert "var" in result
