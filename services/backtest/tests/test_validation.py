"""Tests for out-of-sample validation reporting."""

from __future__ import annotations

from backtest_svc.monte_carlo import (
    ConfidenceInterval,
    MetricDistribution,
    MonteCarloResult,
)
from backtest_svc.sensitivity_sweep import BreakevenAnalysis, SweepPoint, SweepResult
from backtest_svc.validation import (
    ValidationGrade,
    generate_validation_report,
)
from backtest_svc.walk_forward import FoldResult, WalkForwardResult


def _make_wf(
    mean_test_sharpe=1.0,
    overfitting_ratio=1.2,
    degradation_pct=15.0,
    std_test_sharpe=0.3,
) -> WalkForwardResult:
    fold = FoldResult(
        fold_index=0,
        train_sharpe=mean_test_sharpe * overfitting_ratio,
        test_sharpe=mean_test_sharpe,
    )
    return WalkForwardResult(
        folds=[fold],
        mean_test_sharpe=mean_test_sharpe,
        std_test_sharpe=std_test_sharpe,
        overfitting_ratio=overfitting_ratio,
        degradation_pct=degradation_pct,
    )


def _make_mc(
    prob_positive=0.85,
    prob_above_1=0.4,
    ci_low=-0.5,
    ci_high=2.5,
) -> MonteCarloResult:
    return MonteCarloResult(
        n_simulations=1000,
        observed_sharpe=1.0,
        sharpe_distribution=MetricDistribution(
            metric_name="sharpe",
            mean=1.0,
            confidence_intervals=[
                ConfidenceInterval(level=0.05, value=ci_low),
                ConfidenceInterval(level=0.95, value=ci_high),
            ],
        ),
        prob_positive_sharpe=prob_positive,
        prob_sharpe_above_1=prob_above_1,
    )


def _make_sweep(max_fee=0.008, max_slip=15.0) -> SweepResult:
    return SweepResult(
        points=[
            SweepPoint(fee_rate=0.001, sharpe=2.0, total_return=0.10, net_profitable=True),
            SweepPoint(fee_rate=0.01, sharpe=0.5, total_return=0.01, net_profitable=True),
        ],
        breakeven=BreakevenAnalysis(
            max_fee_rate=max_fee,
            max_slippage_bps=max_slip,
        ),
    )


class TestValidationGrade:
    def test_strong_grade(self):
        wf = _make_wf(mean_test_sharpe=1.5, overfitting_ratio=1.1, degradation_pct=8)
        mc = _make_mc(prob_positive=0.92, ci_low=0.5, ci_high=2.5)
        sweep = _make_sweep(max_fee=0.01, max_slip=20.0)

        report = generate_validation_report(wf, mc, sweep)
        assert report.grade == ValidationGrade.STRONG

    def test_fail_grade_severe_overfitting(self):
        wf = _make_wf(
            mean_test_sharpe=-0.5,
            overfitting_ratio=4.0,
            degradation_pct=75,
        )
        mc = _make_mc(prob_positive=0.3)

        report = generate_validation_report(wf, mc)
        assert report.grade in (ValidationGrade.FAIL, ValidationGrade.WEAK)

    def test_weak_grade_one_critical(self):
        wf = _make_wf(mean_test_sharpe=-0.5, overfitting_ratio=1.2, degradation_pct=10)
        mc = _make_mc(prob_positive=0.85)

        report = generate_validation_report(wf, mc)
        # Negative OOS sharpe is critical
        assert report.grade in (ValidationGrade.WEAK, ValidationGrade.FAIL)

    def test_moderate_grade(self):
        wf = _make_wf(mean_test_sharpe=0.8, overfitting_ratio=1.8, degradation_pct=30)
        mc = _make_mc(prob_positive=0.80)

        report = generate_validation_report(wf, mc)
        assert report.grade in (ValidationGrade.MODERATE, ValidationGrade.WEAK)


class TestWalkForwardAssessment:
    def test_low_overfitting_info(self):
        wf = _make_wf(overfitting_ratio=1.1)
        report = generate_validation_report(wf)
        overfitting_flags = [f for f in report.flags if f.category == "overfitting"]
        assert any(f.severity == "info" for f in overfitting_flags)

    def test_moderate_overfitting_warning(self):
        wf = _make_wf(overfitting_ratio=2.0)
        report = generate_validation_report(wf)
        overfitting_flags = [f for f in report.flags if f.category == "overfitting"]
        assert any(f.severity == "warning" for f in overfitting_flags)

    def test_severe_overfitting_critical(self):
        wf = _make_wf(overfitting_ratio=4.0)
        report = generate_validation_report(wf)
        overfitting_flags = [f for f in report.flags if f.category == "overfitting"]
        assert any(f.severity == "critical" for f in overfitting_flags)

    def test_high_degradation_critical(self):
        wf = _make_wf(degradation_pct=60)
        report = generate_validation_report(wf)
        deg_flags = [f for f in report.flags if f.category == "degradation"]
        assert any(f.severity == "critical" for f in deg_flags)

    def test_inconsistent_folds_warning(self):
        wf = _make_wf(std_test_sharpe=1.5)
        report = generate_validation_report(wf)
        cons_flags = [f for f in report.flags if f.category == "consistency"]
        assert any(f.severity == "warning" for f in cons_flags)


class TestMonteCarloAssessment:
    def test_low_prob_positive_critical(self):
        mc = _make_mc(prob_positive=0.4)
        report = generate_validation_report(monte_carlo=mc)
        rob_flags = [f for f in report.flags if f.category == "robustness"]
        assert any(f.severity == "critical" for f in rob_flags)

    def test_high_prob_positive_info(self):
        mc = _make_mc(prob_positive=0.90)
        report = generate_validation_report(monte_carlo=mc)
        rob_flags = [f for f in report.flags if f.category == "robustness"]
        assert any(f.severity == "info" for f in rob_flags)

    def test_wide_ci_warning(self):
        mc = _make_mc(ci_low=-2.0, ci_high=3.0)
        report = generate_validation_report(monte_carlo=mc)
        unc_flags = [f for f in report.flags if f.category == "uncertainty"]
        assert any(f.severity == "warning" for f in unc_flags)


class TestCostAssessment:
    def test_narrow_fee_margin_warning(self):
        sweep = _make_sweep(max_fee=0.004)
        report = generate_validation_report(cost_sensitivity=sweep)
        cost_flags = [f for f in report.flags if f.category == "costs"]
        assert any(f.severity == "warning" for f in cost_flags)

    def test_critical_fee_margin(self):
        sweep = _make_sweep(max_fee=0.002)
        report = generate_validation_report(cost_sensitivity=sweep)
        cost_flags = [f for f in report.flags if f.category == "costs"]
        assert any(f.severity == "critical" for f in cost_flags)

    def test_low_slippage_tolerance(self):
        sweep = _make_sweep(max_slip=3.0)
        report = generate_validation_report(cost_sensitivity=sweep)
        cost_flags = [f for f in report.flags if f.category == "costs"]
        assert any(f.severity == "warning" for f in cost_flags)


class TestReportOutput:
    def test_summary_generated(self):
        wf = _make_wf()
        mc = _make_mc()
        report = generate_validation_report(wf, mc)
        assert len(report.summary) > 0
        assert report.grade.value in report.summary

    def test_key_metrics_extracted(self):
        wf = _make_wf(mean_test_sharpe=1.5, overfitting_ratio=1.3)
        mc = _make_mc(prob_positive=0.85)
        sweep = _make_sweep(max_fee=0.008, max_slip=15.0)

        report = generate_validation_report(wf, mc, sweep)

        assert report.mean_oos_sharpe == 1.5
        assert report.overfitting_ratio == 1.3
        assert report.prob_positive_sharpe == 0.85
        assert report.max_profitable_fee == 0.008

    def test_no_data_warning(self):
        report = generate_validation_report()
        assert any(f.category == "general" for f in report.flags)

    def test_component_results_stored(self):
        wf = _make_wf()
        mc = _make_mc()
        sweep = _make_sweep()

        report = generate_validation_report(wf, mc, sweep)
        assert report.walk_forward is wf
        assert report.monte_carlo is mc
        assert report.cost_sensitivity is sweep
