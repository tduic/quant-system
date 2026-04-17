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
    check_total_exposure,
    check_var,
    drawdown_scale_factor,
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
        assert len(decision.checks_passed) == 5  # position, notional, drawdown, var, total_exposure
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


class TestCheckTotalExposure:
    def test_empty_portfolio_passes(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        # 0.5 * 80000 = 40000 < 500000 default limit
        result = check_total_exposure(signal, flat_state, limits)
        assert result is None

    def test_within_limit_with_existing_positions(self, signal: Signal, limits: RiskLimits):
        state = PortfolioState(
            positions={"BTCUSD": 0.5, "ETHUSD": 2.0},
            peak_equity=100_000.0,
            current_equity=100_000.0,
        )
        prices = {"BTCUSD": 80_000.0, "ETHUSD": 3_000.0}
        # Existing: 0.5*80000 + 2.0*3000 = 46000, plus proposed 0.5*80000 = 40000
        # Total: 86000 < 500000
        result = check_total_exposure(signal, state, limits, latest_prices=prices)
        assert result is None

    def test_exceeds_limit_rejected(self, signal: Signal, limits: RiskLimits):
        limits = RiskLimits(max_total_exposure=50_000.0)
        state = PortfolioState(
            positions={"ETHUSD": 5.0},
            peak_equity=100_000.0,
            current_equity=100_000.0,
        )
        prices = {"ETHUSD": 3_000.0}
        # Existing: 5.0*3000 = 15000, plus proposed 0.5*80000 = 40000
        # Total: 55000 > 50000
        result = check_total_exposure(signal, state, limits, latest_prices=prices)
        assert result is not None
        assert "total_exposure" in result

    def test_no_prices_existing_exposure_zero(self, signal: Signal, flat_state: PortfolioState, limits: RiskLimits):
        """Without price data, existing positions have zero exposure."""
        flat_state.positions["ETHUSD"] = 10.0
        # No prices dict → existing exposure = 0, only proposed counts
        result = check_total_exposure(signal, flat_state, limits)
        assert result is None  # 40000 < 500000

    def test_multi_symbol_exposure_aggregated(self, signal: Signal, limits: RiskLimits):
        limits = RiskLimits(max_total_exposure=200_000.0)
        state = PortfolioState(
            positions={"BTCUSD": 1.0, "ETHUSD": 10.0, "SOLUSD": 100.0},
            peak_equity=100_000.0,
            current_equity=100_000.0,
        )
        prices = {"BTCUSD": 80_000.0, "ETHUSD": 3_000.0, "SOLUSD": 150.0}
        # Existing: 80000 + 30000 + 15000 = 125000, plus 40000 = 165000 < 200000
        result = check_total_exposure(signal, state, limits, latest_prices=prices)
        assert result is None


class TestDrawdownScaleFactor:
    def test_no_drawdown_full_size(self):
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=100_000)
        assert drawdown_scale_factor(state, RiskLimits()) == 1.0

    def test_small_drawdown_full_size(self):
        """Under 3% drawdown → no scaling."""
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=98_000)
        assert drawdown_scale_factor(state, RiskLimits()) == 1.0

    def test_moderate_drawdown_scales_down(self):
        """Between 3% and 7% drawdown → linearly scale from 1.0 to 0.25."""
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=95_000)
        scale = drawdown_scale_factor(state, RiskLimits())
        assert 0.25 < scale < 1.0
        # At 5% drawdown: 1.0 - (0.05 - 0.03) / 0.04 * 0.75 = 1.0 - 0.375 = 0.625
        assert scale == pytest.approx(0.625)

    def test_at_3pct_boundary(self):
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=97_000)
        assert drawdown_scale_factor(state, RiskLimits()) == 1.0

    def test_at_7pct_boundary(self):
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=93_000)
        assert drawdown_scale_factor(state, RiskLimits()) == pytest.approx(0.25)

    def test_deep_drawdown_minimum_size(self):
        """Between 7% and 10% drawdown → fixed 0.25x."""
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=92_000)
        assert drawdown_scale_factor(state, RiskLimits()) == 0.25

    def test_zero_peak_equity_full_size(self):
        state = PortfolioState(positions={}, peak_equity=0, current_equity=0)
        assert drawdown_scale_factor(state, RiskLimits()) == 1.0

    def test_run_risk_checks_applies_scale(self):
        """run_risk_checks should multiply quantity by drawdown scale factor."""
        signal = Signal(
            strategy_id="test",
            symbol="BTCUSD",
            side="BUY",
            strength=0.8,
            target_quantity=1.0,
            mid_price_at_signal=100.0,
            spread_at_signal=1.0,
        )
        # 5% drawdown → scale = 0.625
        state = PortfolioState(positions={}, peak_equity=100_000, current_equity=95_000)
        limits = RiskLimits(max_drawdown_pct=0.10)
        decision = run_risk_checks(signal, state, limits)
        assert decision.decision == "APPROVED"
        assert decision.adjusted_quantity == pytest.approx(0.625)
        assert "scaled_by_drawdown" in decision.reason
