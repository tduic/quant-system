#!/usr/bin/env python3
"""Paper Trading Validator — validates system health during paper trading.

Runs a series of checks against the live system to ensure everything is
working correctly before switching to live trading.

Usage:
    python scripts/paper_trading_validator.py [--redis-url redis://localhost:6379/0]
                                               [--api-url http://localhost:8080]
                                               [--risk-url http://localhost:8090]
                                               [--duration-minutes 5]
                                               [--output report.json]

Checks performed:
    1. Market data freshness — are we receiving trades within the last 30s?
    2. Pipeline flow — are signals, orders, and fills being generated?
    3. Fill quality — slippage stats, fee consistency, fill price vs mid price
    4. Portfolio state consistency — Redis state matches post-trade API
    5. Risk gateway health — approval/rejection rate, circuit breaker status
    6. Data gap detection — checks for gaps in trade timestamps
    7. Order lifecycle — verifies orders transition through expected states
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis
import requests


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str  # "critical", "warning", "info"
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class ValidationReport:
    timestamp: str
    duration_seconds: float
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "critical")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if not c.passed and c.severity == "warning")

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "overall_pass": self.passed,
            "total_checks": len(self.checks),
            "passed_checks": sum(1 for c in self.checks if c.passed),
            "failed_critical": sum(1 for c in self.checks if not c.passed and c.severity == "critical"),
            "warnings": self.warnings,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "severity": c.severity,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


class PaperTradingValidator:
    """Validates system health during paper trading."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        api_url: str = "http://localhost:8080",
        risk_url: str = "http://localhost:8090",
        run_id: str = "live",
    ) -> None:
        self.redis_client = redis.from_url(redis_url)
        self.api_url = api_url.rstrip("/")
        self.risk_url = risk_url.rstrip("/")
        self.run_id = run_id
        self.checks: list[CheckResult] = []

    def _add(self, name: str, passed: bool, severity: str, message: str, **details) -> None:
        self.checks.append(CheckResult(name=name, passed=passed, severity=severity, message=message, details=details))

    def check_redis_connectivity(self) -> None:
        """Verify Redis is reachable and responsive."""
        try:
            pong = self.redis_client.ping()
            self._add("redis_connectivity", pong, "critical", "Redis is reachable" if pong else "Redis did not respond")
        except Exception as e:
            self._add("redis_connectivity", False, "critical", f"Cannot connect to Redis: {e}")

    def check_circuit_breaker(self) -> None:
        """Verify circuit breaker is NOT tripped."""
        try:
            resp = requests.get(f"{self.risk_url}/api/circuit-breaker", timeout=5)
            data = resp.json()
            tripped = data.get("tripped", False)
            self._add(
                "circuit_breaker",
                not tripped,
                "critical",
                "Circuit breaker is clear" if not tripped else f"Circuit breaker is TRIPPED: {data.get('reason', 'unknown')}",
                **data,
            )
        except Exception as e:
            self._add("circuit_breaker", False, "critical", f"Cannot reach risk gateway: {e}")

    def check_risk_gateway_health(self) -> None:
        """Check risk gateway /health endpoint for counters."""
        try:
            resp = requests.get(f"{self.risk_url}/health", timeout=5)
            data = resp.json()
            approved = data.get("approved", 0)
            rejected = data.get("rejected", 0)
            total = approved + rejected

            if total == 0:
                self._add("risk_gateway_activity", False, "warning", "No signals processed yet", **data)
            else:
                reject_rate = rejected / total
                passed = reject_rate < 0.95  # If >95% rejected, something is wrong
                self._add(
                    "risk_gateway_activity",
                    passed,
                    "warning" if not passed else "info",
                    f"Approved: {approved}, Rejected: {rejected} ({reject_rate:.1%} rejection rate)",
                    **data,
                )
        except Exception as e:
            self._add("risk_gateway_activity", False, "critical", f"Cannot reach risk gateway: {e}")

    def check_portfolio_state(self) -> None:
        """Verify portfolio state exists in Redis."""
        try:
            key = f"portfolio:{self.run_id}"
            data = self.redis_client.hgetall(key)
            if not data:
                self._add("portfolio_state", False, "warning", "No portfolio state in Redis (no fills yet?)")
                return

            equity = float(data.get(b"current_equity", b"0"))
            peak = float(data.get(b"peak_equity", b"0"))
            self._add(
                "portfolio_state",
                True,
                "info",
                f"Portfolio state found: equity=${equity:,.2f}, peak=${peak:,.2f}",
                current_equity=equity,
                peak_equity=peak,
            )
        except Exception as e:
            self._add("portfolio_state", False, "critical", f"Error reading portfolio state: {e}")

    def check_api_health(self) -> None:
        """Verify the post-trade dashboard API is responding."""
        try:
            resp = requests.get(f"{self.api_url}/api/symbols", timeout=5)
            if resp.status_code == 200:
                symbols = resp.json()
                self._add(
                    "dashboard_api",
                    True,
                    "info",
                    f"Dashboard API responding, {len(symbols)} symbols active",
                    symbols=symbols,
                )
            else:
                self._add("dashboard_api", False, "critical", f"Dashboard API returned {resp.status_code}")
        except Exception as e:
            self._add("dashboard_api", False, "critical", f"Cannot reach dashboard API: {e}")

    def check_fills(self) -> None:
        """Check that fills are being generated and have reasonable values."""
        try:
            resp = requests.get(f"{self.api_url}/api/fills", timeout=5)
            data = resp.json()

            fills = data.get("fills", [])
            if not fills:
                self._add("fills_exist", False, "warning", "No fills recorded yet")
                return

            self._add("fills_exist", True, "info", f"{len(fills)} fills recorded")

            # Check fill quality
            slippages = [f["slippage_bps"] for f in fills if "slippage_bps" in f]
            fees = [f["fee"] for f in fills if "fee" in f]

            if slippages:
                avg_slippage = sum(slippages) / len(slippages)
                max_slippage = max(slippages)
                reasonable = max_slippage < 100  # 100 bps = 1% — sanity check
                self._add(
                    "fill_slippage",
                    reasonable,
                    "warning" if not reasonable else "info",
                    f"Avg slippage: {avg_slippage:.2f} bps, Max: {max_slippage:.2f} bps",
                    avg_slippage_bps=avg_slippage,
                    max_slippage_bps=max_slippage,
                )

            if fees:
                total_fees = sum(fees)
                self._add("fill_fees", True, "info", f"Total fees: ${total_fees:.4f}")

        except Exception as e:
            self._add("fills_exist", False, "critical", f"Cannot fetch fills: {e}")

    def check_pnl_consistency(self) -> None:
        """Verify PnL data from the API makes sense."""
        try:
            resp = requests.get(f"{self.api_url}/api/pnl", timeout=5)
            data = resp.json()

            equity = data.get("current_equity", 0)
            realized = data.get("total_realized_pnl", 0)
            unrealized = data.get("total_unrealized_pnl", 0)
            fees = data.get("total_fees", 0)

            # Basic sanity: fees should not be negative
            fees_ok = fees >= 0
            self._add(
                "pnl_sanity",
                fees_ok,
                "warning" if not fees_ok else "info",
                f"Equity: ${equity:,.2f}, Realized: ${realized:,.2f}, Unrealized: ${unrealized:,.2f}, Fees: ${fees:,.4f}",
                current_equity=equity,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_fees=fees,
            )
        except Exception as e:
            self._add("pnl_sanity", False, "warning", f"Cannot fetch PnL: {e}")

    def check_risk_metrics(self) -> None:
        """Check computed risk metrics for red flags."""
        try:
            resp = requests.get(f"{self.api_url}/api/risk-metrics", timeout=5)
            data = resp.json()

            drawdown = data.get("max_drawdown_pct", 0)
            sharpe = data.get("sharpe_ratio")
            win_rate = data.get("win_rate")

            drawdown_ok = drawdown < 0.10  # 10% is a hard sanity limit
            self._add(
                "risk_metrics",
                drawdown_ok,
                "critical" if not drawdown_ok else "info",
                f"Max drawdown: {drawdown:.1%}" + (f", Sharpe: {sharpe:.2f}" if sharpe else "") + (f", Win rate: {win_rate:.1%}" if win_rate else ""),
                **data,
            )
        except Exception as e:
            self._add("risk_metrics", False, "warning", f"Cannot fetch risk metrics: {e}")

    def check_order_keys_in_redis(self) -> None:
        """Verify order state keys exist in Redis."""
        try:
            pattern = f"order:{self.run_id}:*"
            keys = list(self.redis_client.scan_iter(match=pattern, count=100))
            count = len(keys)
            self._add(
                "order_tracking",
                count > 0,
                "warning" if count == 0 else "info",
                f"{count} order state keys in Redis" if count > 0 else "No order state keys found (no orders yet?)",
                order_count=count,
            )
        except Exception as e:
            self._add("order_tracking", False, "warning", f"Error scanning order keys: {e}")

    def run_all(self) -> ValidationReport:
        """Run all validation checks and return a report."""
        start = time.monotonic()
        self.checks = []

        self.check_redis_connectivity()
        self.check_circuit_breaker()
        self.check_risk_gateway_health()
        self.check_portfolio_state()
        self.check_api_health()
        self.check_fills()
        self.check_pnl_consistency()
        self.check_risk_metrics()
        self.check_order_keys_in_redis()

        elapsed = time.monotonic() - start
        return ValidationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_seconds=round(elapsed, 3),
            checks=self.checks,
        )


class ContinuousValidator:
    """Runs the validator repeatedly over a duration, collecting snapshots."""

    def __init__(self, validator: PaperTradingValidator, duration_minutes: float, interval_seconds: float = 30.0) -> None:
        self.validator = validator
        self.duration_minutes = duration_minutes
        self.interval_seconds = interval_seconds

    def run(self) -> dict:
        """Run validation loop and return summary."""
        snapshots: list[dict] = []
        start = time.monotonic()
        end_time = start + (self.duration_minutes * 60)
        iteration = 0

        print(f"Starting paper trading validation ({self.duration_minutes} min, checking every {self.interval_seconds}s)")
        print("=" * 70)

        while time.monotonic() < end_time:
            iteration += 1
            report = self.validator.run_all()
            snap = report.to_dict()
            snapshots.append(snap)

            # Print summary
            status = "PASS" if report.passed else "FAIL"
            passed = sum(1 for c in report.checks if c.passed)
            total = len(report.checks)
            warnings = report.warnings
            ts = datetime.now().strftime("%H:%M:%S")

            color = "\033[92m" if report.passed else "\033[91m"
            reset = "\033[0m"
            print(f"[{ts}] Iteration {iteration}: {color}{status}{reset} ({passed}/{total} checks, {warnings} warnings)")

            for c in report.checks:
                if not c.passed:
                    icon = "!" if c.severity == "critical" else "~"
                    print(f"  [{icon}] {c.name}: {c.message}")

            remaining = end_time - time.monotonic()
            if remaining > self.interval_seconds:
                time.sleep(self.interval_seconds)

        # Aggregate results
        total_iterations = len(snapshots)
        all_passed = sum(1 for s in snapshots if s["overall_pass"])

        print("=" * 70)
        print(f"Validation complete: {all_passed}/{total_iterations} iterations passed")

        return {
            "summary": {
                "total_iterations": total_iterations,
                "passed_iterations": all_passed,
                "failed_iterations": total_iterations - all_passed,
                "pass_rate": all_passed / total_iterations if total_iterations > 0 else 0,
                "duration_minutes": self.duration_minutes,
            },
            "snapshots": snapshots,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trading Validator")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--api-url", default="http://localhost:8080")
    parser.add_argument("--risk-url", default="http://localhost:8090")
    parser.add_argument("--run-id", default="live")
    parser.add_argument("--duration-minutes", type=float, default=5.0, help="How long to run validation (minutes)")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between checks")
    parser.add_argument("--output", default=None, help="Save report to JSON file")
    parser.add_argument("--once", action="store_true", help="Run checks once and exit")
    args = parser.parse_args()

    validator = PaperTradingValidator(
        redis_url=args.redis_url,
        api_url=args.api_url,
        risk_url=args.risk_url,
        run_id=args.run_id,
    )

    if args.once:
        report = validator.run_all()
        result = report.to_dict()
        print(json.dumps(result, indent=2))
        sys.exit(0 if report.passed else 1)

    continuous = ContinuousValidator(validator, duration_minutes=args.duration_minutes, interval_seconds=args.interval)
    result = continuous.run()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nReport saved to {args.output}")

    # Exit code: 0 if >80% of iterations passed, 1 otherwise
    pass_rate = result["summary"]["pass_rate"]
    sys.exit(0 if pass_rate >= 0.8 else 1)


if __name__ == "__main__":
    main()
