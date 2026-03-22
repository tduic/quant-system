"""Out-of-sample validation reporting.

Combines walk-forward results, Monte Carlo confidence intervals, and
sensitivity analysis into a single validation report that answers:
"Should I trust this backtest?"

Red flags:
    - High overfitting ratio (train >> test performance)
    - Wide Monte Carlo confidence intervals on Sharpe
    - Performance collapses with small fee/slippage increases
    - Inconsistent fold performance (high std across folds)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest_svc.monte_carlo import MonteCarloResult
    from backtest_svc.sensitivity_sweep import SweepResult
    from backtest_svc.walk_forward import WalkForwardResult

logger = logging.getLogger(__name__)


class ValidationGrade(StrEnum):
    """Overall assessment grade."""

    STRONG = "STRONG"  # robust across all tests
    MODERATE = "MODERATE"  # some concerns but tradeable
    WEAK = "WEAK"  # significant issues
    FAIL = "FAIL"  # do not trade


@dataclass
class ValidationFlag:
    """A specific concern or positive indicator."""

    category: str = ""  # e.g., "overfitting", "robustness", "costs"
    severity: str = "info"  # "info", "warning", "critical"
    message: str = ""


@dataclass
class ValidationReport:
    """Comprehensive out-of-sample validation report."""

    grade: ValidationGrade = ValidationGrade.MODERATE
    flags: list[ValidationFlag] = field(default_factory=list)
    summary: str = ""

    # Component results
    walk_forward: WalkForwardResult | None = None
    monte_carlo: MonteCarloResult | None = None
    cost_sensitivity: SweepResult | None = None

    # Key metrics (extracted for convenience)
    mean_oos_sharpe: float = 0.0
    sharpe_95_ci_low: float = 0.0
    sharpe_95_ci_high: float = 0.0
    overfitting_ratio: float = 0.0
    degradation_pct: float = 0.0
    max_profitable_fee: float = 0.0
    max_profitable_slippage_bps: float = 0.0
    prob_positive_sharpe: float = 0.0


def _assess_walk_forward(
    wf: WalkForwardResult,
    flags: list[ValidationFlag],
) -> None:
    """Assess walk-forward results and add flags."""
    if not wf.folds:
        flags.append(ValidationFlag("walk_forward", "warning", "No walk-forward folds available"))
        return

    # Overfitting check
    if wf.overfitting_ratio > 3.0:
        flags.append(
            ValidationFlag(
                "overfitting",
                "critical",
                f"Severe overfitting: train/test Sharpe ratio = {wf.overfitting_ratio:.1f}x",
            )
        )
    elif wf.overfitting_ratio > 1.5:
        flags.append(
            ValidationFlag(
                "overfitting",
                "warning",
                f"Moderate overfitting: train/test Sharpe ratio = {wf.overfitting_ratio:.1f}x",
            )
        )
    else:
        flags.append(
            ValidationFlag(
                "overfitting",
                "info",
                f"Low overfitting: train/test ratio = {wf.overfitting_ratio:.1f}x",
            )
        )

    # Degradation check
    if wf.degradation_pct > 50:
        flags.append(
            ValidationFlag(
                "degradation",
                "critical",
                f"Performance degrades {wf.degradation_pct:.0f}% out-of-sample",
            )
        )
    elif wf.degradation_pct > 25:
        flags.append(
            ValidationFlag(
                "degradation",
                "warning",
                f"Performance degrades {wf.degradation_pct:.0f}% out-of-sample",
            )
        )

    # Consistency check (std of test Sharpe across folds)
    if wf.std_test_sharpe > 1.0:
        flags.append(
            ValidationFlag(
                "consistency",
                "warning",
                f"Inconsistent fold performance: Sharpe std = {wf.std_test_sharpe:.2f}",
            )
        )

    # Mean OOS Sharpe
    if wf.mean_test_sharpe < 0:
        flags.append(
            ValidationFlag(
                "performance",
                "critical",
                f"Negative out-of-sample Sharpe: {wf.mean_test_sharpe:.2f}",
            )
        )
    elif wf.mean_test_sharpe < 0.5:
        flags.append(
            ValidationFlag(
                "performance",
                "warning",
                f"Low out-of-sample Sharpe: {wf.mean_test_sharpe:.2f}",
            )
        )


def _assess_monte_carlo(
    mc: MonteCarloResult,
    flags: list[ValidationFlag],
) -> None:
    """Assess Monte Carlo results and add flags."""
    if mc.n_simulations == 0:
        flags.append(ValidationFlag("monte_carlo", "warning", "No Monte Carlo simulations run"))
        return

    # Probability of positive Sharpe
    if mc.prob_positive_sharpe < 0.5:
        flags.append(
            ValidationFlag(
                "robustness",
                "critical",
                f"Only {mc.prob_positive_sharpe:.0%} chance of positive Sharpe",
            )
        )
    elif mc.prob_positive_sharpe < 0.75:
        flags.append(
            ValidationFlag(
                "robustness",
                "warning",
                f"{mc.prob_positive_sharpe:.0%} chance of positive Sharpe",
            )
        )
    else:
        flags.append(
            ValidationFlag(
                "robustness",
                "info",
                f"{mc.prob_positive_sharpe:.0%} chance of positive Sharpe",
            )
        )

    # Sharpe confidence interval width
    dist = mc.sharpe_distribution
    if dist.confidence_intervals:
        ci_low = next((ci.value for ci in dist.confidence_intervals if ci.level == 0.05), 0.0)
        ci_high = next((ci.value for ci in dist.confidence_intervals if ci.level == 0.95), 0.0)
        width = ci_high - ci_low
        if width > 3.0:
            flags.append(
                ValidationFlag(
                    "uncertainty",
                    "warning",
                    f"Wide Sharpe CI: [{ci_low:.2f}, {ci_high:.2f}] (width={width:.2f})",
                )
            )


def _assess_cost_sensitivity(
    sweep: SweepResult,
    flags: list[ValidationFlag],
) -> None:
    """Assess cost sensitivity results and add flags."""
    if not sweep.points:
        flags.append(ValidationFlag("costs", "warning", "No cost sensitivity data"))
        return

    be = sweep.breakeven

    # Fee breakeven
    if be.max_fee_rate > 0 and be.max_fee_rate < 0.003:
        flags.append(
            ValidationFlag(
                "costs",
                "critical",
                f"Strategy breaks even at only {be.max_fee_rate:.1%} fee rate",
            )
        )
    elif be.max_fee_rate > 0 and be.max_fee_rate < 0.006:
        flags.append(
            ValidationFlag(
                "costs",
                "warning",
                f"Narrow fee margin: breaks even at {be.max_fee_rate:.1%}",
            )
        )

    # Slippage breakeven
    if be.max_slippage_bps > 0 and be.max_slippage_bps < 5.0:
        flags.append(
            ValidationFlag(
                "costs",
                "warning",
                f"Sensitive to slippage: breaks even at {be.max_slippage_bps:.1f} bps",
            )
        )


def _compute_grade(flags: list[ValidationFlag]) -> ValidationGrade:
    """Determine overall grade from flags."""
    critical_count = sum(1 for f in flags if f.severity == "critical")
    warning_count = sum(1 for f in flags if f.severity == "warning")

    if critical_count >= 2:
        return ValidationGrade.FAIL
    if critical_count == 1:
        return ValidationGrade.WEAK
    if warning_count >= 3:
        return ValidationGrade.WEAK
    if warning_count >= 1:
        return ValidationGrade.MODERATE
    return ValidationGrade.STRONG


def generate_validation_report(
    walk_forward: WalkForwardResult | None = None,
    monte_carlo: MonteCarloResult | None = None,
    cost_sensitivity: SweepResult | None = None,
) -> ValidationReport:
    """Generate a comprehensive out-of-sample validation report.

    Combines results from walk-forward optimization, Monte Carlo
    simulation, and cost sensitivity analysis into a single assessment.

    Args:
        walk_forward: Walk-forward optimization results.
        monte_carlo: Monte Carlo simulation results.
        cost_sensitivity: Slippage/fee sweep results.

    Returns:
        ValidationReport with grade, flags, and key metrics.
    """
    flags: list[ValidationFlag] = []

    if walk_forward is not None:
        _assess_walk_forward(walk_forward, flags)

    if monte_carlo is not None:
        _assess_monte_carlo(monte_carlo, flags)

    if cost_sensitivity is not None:
        _assess_cost_sensitivity(cost_sensitivity, flags)

    if not flags:
        flags.append(ValidationFlag("general", "warning", "No validation data provided"))

    grade = _compute_grade(flags)

    # Extract key metrics
    report = ValidationReport(
        grade=grade,
        flags=flags,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        cost_sensitivity=cost_sensitivity,
    )

    if walk_forward and walk_forward.folds:
        report.mean_oos_sharpe = walk_forward.mean_test_sharpe
        report.overfitting_ratio = walk_forward.overfitting_ratio
        report.degradation_pct = walk_forward.degradation_pct

    if monte_carlo and monte_carlo.n_simulations > 0:
        report.prob_positive_sharpe = monte_carlo.prob_positive_sharpe
        dist = monte_carlo.sharpe_distribution
        if dist.confidence_intervals:
            report.sharpe_95_ci_low = next(
                (ci.value for ci in dist.confidence_intervals if ci.level == 0.05),
                0.0,
            )
            report.sharpe_95_ci_high = next(
                (ci.value for ci in dist.confidence_intervals if ci.level == 0.95),
                0.0,
            )

    if cost_sensitivity and cost_sensitivity.breakeven:
        report.max_profitable_fee = cost_sensitivity.breakeven.max_fee_rate
        report.max_profitable_slippage_bps = cost_sensitivity.breakeven.max_slippage_bps

    # Generate summary
    report.summary = _generate_summary(report)

    return report


def _generate_summary(report: ValidationReport) -> str:
    """Generate a human-readable summary."""
    parts = [f"Validation Grade: {report.grade.value}"]

    if report.mean_oos_sharpe != 0:
        parts.append(f"Out-of-sample Sharpe: {report.mean_oos_sharpe:.2f}")

    if report.prob_positive_sharpe > 0:
        parts.append(f"P(Sharpe > 0): {report.prob_positive_sharpe:.0%}")

    if report.overfitting_ratio > 0:
        parts.append(f"Overfitting ratio: {report.overfitting_ratio:.1f}x")

    critical = [f for f in report.flags if f.severity == "critical"]
    if critical:
        parts.append(f"Critical issues: {len(critical)}")
        for f in critical:
            parts.append(f"  - {f.message}")

    return " | ".join(parts[:4]) + ("\n" + "\n".join(parts[4:]) if len(parts) > 4 else "")
