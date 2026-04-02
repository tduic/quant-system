"""Tests for paper_trading_validator — validates system health during paper trading."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from paper_trading_validator import (
    CheckResult,
    ContinuousValidator,
    PaperTradingValidator,
    ValidationReport,
)


class TestCheckResult:
    """Test CheckResult dataclass."""

    def test_check_result_creation(self):
        result = CheckResult(
            name="test_check",
            passed=True,
            severity="critical",
            message="Test passed",
            details={"key": "value"},
        )
        assert result.name == "test_check"
        assert result.passed is True
        assert result.severity == "critical"
        assert result.message == "Test passed"
        assert result.details == {"key": "value"}


class TestValidationReport:
    """Test ValidationReport dataclass."""

    def test_passed_all_critical_checks_pass(self):
        checks = [
            CheckResult("check1", True, "critical", "passed"),
            CheckResult("check2", True, "critical", "passed"),
        ]
        report = ValidationReport(timestamp="2026-04-01T00:00:00", duration_seconds=1.0, checks=checks)
        assert report.passed is True

    def test_passed_fails_when_critical_check_fails(self):
        checks = [
            CheckResult("check1", True, "critical", "passed"),
            CheckResult("check2", False, "critical", "failed"),
        ]
        report = ValidationReport(timestamp="2026-04-01T00:00:00", duration_seconds=1.0, checks=checks)
        assert report.passed is False

    def test_passed_ignores_failed_warning_checks(self):
        checks = [
            CheckResult("check1", True, "critical", "passed"),
            CheckResult("check2", False, "warning", "failed warning"),
        ]
        report = ValidationReport(timestamp="2026-04-01T00:00:00", duration_seconds=1.0, checks=checks)
        assert report.passed is True

    def test_warnings_counts_failed_warning_checks(self):
        checks = [
            CheckResult("check1", True, "critical", "passed"),
            CheckResult("check2", False, "warning", "failed warning 1"),
            CheckResult("check3", False, "warning", "failed warning 2"),
            CheckResult("check4", True, "warning", "passed warning"),
        ]
        report = ValidationReport(timestamp="2026-04-01T00:00:00", duration_seconds=1.0, checks=checks)
        assert report.warnings == 2

    def test_to_dict_produces_valid_structure(self):
        checks = [
            CheckResult("check1", True, "critical", "passed", {"detail1": "value1"}),
            CheckResult("check2", False, "warning", "failed", {"detail2": "value2"}),
        ]
        report = ValidationReport(timestamp="2026-04-01T00:00:00", duration_seconds=2.5, checks=checks)

        result = report.to_dict()
        assert result["timestamp"] == "2026-04-01T00:00:00"
        assert result["duration_seconds"] == 2.5
        assert result["overall_pass"] is True
        assert result["total_checks"] == 2
        assert result["passed_checks"] == 1
        assert result["failed_critical"] == 0
        assert result["warnings"] == 1
        assert len(result["checks"]) == 2
        assert result["checks"][0]["name"] == "check1"
        assert result["checks"][0]["passed"] is True
        assert result["checks"][0]["severity"] == "critical"
        assert result["checks"][0]["message"] == "passed"
        assert result["checks"][0]["details"]["detail1"] == "value1"


class TestPaperTradingValidator:
    """Test PaperTradingValidator check methods."""

    def test_init_sets_urls(self):
        validator = PaperTradingValidator(
            redis_url="redis://test:6379/0",
            api_url="http://test:8080/",
            risk_url="http://test:8090/",
        )
        assert validator.api_url == "http://test:8080"
        assert validator.risk_url == "http://test:8090"

    def test_init_strips_trailing_slashes(self):
        validator = PaperTradingValidator(
            api_url="http://test:8080///",
            risk_url="http://test:8090/",
        )
        assert validator.api_url == "http://test:8080"
        assert validator.risk_url == "http://test:8090"

    @patch("paper_trading_validator.redis.from_url")
    def test_check_redis_connectivity_passes_when_ping_returns_true(self, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis_factory.return_value = mock_redis

        validator = PaperTradingValidator()
        validator.check_redis_connectivity()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.name == "redis_connectivity"
        assert result.passed is True
        assert result.severity == "critical"

    @patch("paper_trading_validator.redis.from_url")
    def test_check_redis_connectivity_fails_when_exception_raised(self, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = Exception("Connection refused")
        mock_redis_factory.return_value = mock_redis

        validator = PaperTradingValidator()
        validator.check_redis_connectivity()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.name == "redis_connectivity"
        assert result.passed is False
        assert result.severity == "critical"
        assert "Connection refused" in result.message

    @patch("paper_trading_validator.requests.get")
    def test_check_circuit_breaker_passes_when_not_tripped(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"tripped": False, "reason": None}
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_circuit_breaker()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.name == "circuit_breaker"
        assert result.passed is True
        assert result.severity == "critical"

    @patch("paper_trading_validator.requests.get")
    def test_check_circuit_breaker_fails_when_tripped(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"tripped": True, "reason": "excessive_losses"}
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_circuit_breaker()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.name == "circuit_breaker"
        assert result.passed is False
        assert result.severity == "critical"
        assert "TRIPPED" in result.message

    @patch("paper_trading_validator.requests.get")
    def test_check_circuit_breaker_fails_on_request_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")

        validator = PaperTradingValidator()
        validator.check_circuit_breaker()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.passed is False
        assert "Cannot reach risk gateway" in result.message

    @patch("paper_trading_validator.requests.get")
    def test_check_risk_gateway_health_reports_high_rejection_rate_as_warning(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "approved": 5,
            "rejected": 950,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_risk_gateway_health()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.name == "risk_gateway_activity"
        assert result.passed is False
        assert result.severity == "warning"
        assert "95.0%" in result.message or "95" in result.message

    @patch("paper_trading_validator.requests.get")
    def test_check_risk_gateway_health_passes_with_reasonable_rejection_rate(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "approved": 95,
            "rejected": 5,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_risk_gateway_health()

        assert len(validator.checks) == 1
        result = validator.checks[0]
        assert result.passed is True

    @patch("paper_trading_validator.requests.get")
    def test_check_fills_reports_slippage_stats_correctly(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "fills": [
                {"slippage_bps": 1.5, "fee": 0.01},
                {"slippage_bps": 2.0, "fee": 0.02},
                {"slippage_bps": 0.5, "fee": 0.01},
            ]
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_fills()

        # Check that both fills_exist and fill_slippage checks were recorded
        slippage_check = next((c for c in validator.checks if c.name == "fill_slippage"), None)
        assert slippage_check is not None
        assert slippage_check.passed is True
        assert slippage_check.details["avg_slippage_bps"] == pytest.approx((1.5 + 2.0 + 0.5) / 3)
        assert slippage_check.details["max_slippage_bps"] == pytest.approx(2.0)

    @patch("paper_trading_validator.requests.get")
    def test_check_fills_records_zero_fills_as_warning(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {"fills": []}
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_fills()

        result = validator.checks[0]
        assert result.name == "fills_exist"
        assert result.passed is False
        assert result.severity == "warning"

    @patch("paper_trading_validator.requests.get")
    def test_check_pnl_consistency_detects_negative_fees(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "current_equity": 10000.0,
            "total_realized_pnl": 100.0,
            "total_unrealized_pnl": 50.0,
            "total_fees": -10.0,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_pnl_consistency()

        result = validator.checks[0]
        assert result.name == "pnl_sanity"
        assert result.passed is False
        assert result.severity == "warning"

    @patch("paper_trading_validator.requests.get")
    def test_check_pnl_consistency_passes_with_valid_fees(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = {
            "current_equity": 10000.0,
            "total_realized_pnl": 100.0,
            "total_unrealized_pnl": 50.0,
            "total_fees": 0.5,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        validator.check_pnl_consistency()

        result = validator.checks[0]
        assert result.name == "pnl_sanity"
        assert result.passed is True

    @patch("paper_trading_validator.redis.from_url")
    @patch("paper_trading_validator.requests.get")
    def test_run_all_returns_validation_report(self, mock_get, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.hgetall.return_value = {}
        mock_redis.scan_iter.return_value = []
        mock_redis_factory.return_value = mock_redis

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tripped": False,
            "approved": 100,
            "rejected": 10,
            "symbols": ["BTC", "ETH"],
            "fills": [],
            "current_equity": 10000.0,
            "total_realized_pnl": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "max_drawdown_pct": 0.01,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        report = validator.run_all()

        assert isinstance(report, ValidationReport)
        assert report.timestamp is not None
        assert report.duration_seconds >= 0
        assert len(report.checks) > 0

    @patch("paper_trading_validator.redis.from_url")
    @patch("paper_trading_validator.requests.get")
    def test_run_all_includes_all_check_names(self, mock_get, mock_redis_factory):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.hgetall.return_value = {}
        mock_redis.scan_iter.return_value = []
        mock_redis_factory.return_value = mock_redis

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tripped": False,
            "approved": 100,
            "rejected": 10,
            "symbols": [],
            "fills": [],
            "current_equity": 10000.0,
            "total_realized_pnl": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "max_drawdown_pct": 0.01,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        report = validator.run_all()

        check_names = {c.name for c in report.checks}
        expected_names = {
            "redis_connectivity",
            "circuit_breaker",
            "risk_gateway_activity",
            "portfolio_state",
            "dashboard_api",
            "fills_exist",
            "pnl_sanity",
            "risk_metrics",
            "order_tracking",
        }
        assert expected_names.issubset(check_names)


class TestContinuousValidator:
    """Test ContinuousValidator."""

    @patch("paper_trading_validator.time.monotonic")
    @patch("paper_trading_validator.time.sleep")
    @patch("paper_trading_validator.redis.from_url")
    @patch("paper_trading_validator.requests.get")
    def test_run_executes_multiple_iterations(self, mock_get, mock_redis_factory, mock_sleep, mock_monotonic):
        # Mock time: start at 0, first iteration at 0, loop check at 31, sleep, second at 31, check at 62, sleep, check at 200 (exit)
        times = [0, 0, 31, 31, 62, 62, 200]
        call_count = [0]

        def monotonic_side_effect():
            result = times[call_count[0]] if call_count[0] < len(times) else 200
            call_count[0] += 1
            return result

        mock_monotonic.side_effect = monotonic_side_effect

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.hgetall.return_value = {}
        mock_redis.scan_iter.return_value = []
        mock_redis_factory.return_value = mock_redis

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tripped": False,
            "approved": 100,
            "rejected": 10,
            "symbols": [],
            "fills": [],
            "current_equity": 10000.0,
            "total_realized_pnl": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "max_drawdown_pct": 0.01,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        continuous = ContinuousValidator(validator, duration_minutes=2, interval_seconds=30)
        result = continuous.run()

        assert "summary" in result
        assert "snapshots" in result
        assert result["summary"]["total_iterations"] >= 1
        assert result["summary"]["passed_iterations"] >= 0
        assert result["summary"]["failed_iterations"] >= 0

    @patch("paper_trading_validator.time.monotonic")
    @patch("paper_trading_validator.time.sleep")
    @patch("paper_trading_validator.redis.from_url")
    @patch("paper_trading_validator.requests.get")
    def test_run_calculates_pass_rate(self, mock_get, mock_redis_factory, mock_sleep, mock_monotonic):
        times = [0, 0, 31, 31, 100]
        call_count = [0]

        def monotonic_side_effect():
            result = times[call_count[0]] if call_count[0] < len(times) else 100
            call_count[0] += 1
            return result

        mock_monotonic.side_effect = monotonic_side_effect

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.hgetall.return_value = {}
        mock_redis.scan_iter.return_value = []
        mock_redis_factory.return_value = mock_redis

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tripped": False,
            "approved": 100,
            "rejected": 10,
            "symbols": [],
            "fills": [],
            "current_equity": 10000.0,
            "total_realized_pnl": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_fees": 0.0,
            "max_drawdown_pct": 0.01,
        }
        mock_get.return_value = mock_response

        validator = PaperTradingValidator()
        continuous = ContinuousValidator(validator, duration_minutes=1, interval_seconds=30)
        result = continuous.run()

        pass_rate = result["summary"]["pass_rate"]
        assert 0 <= pass_rate <= 1
