"""Tests for quant_core.reconciliation — position reconciliation logic."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from quant_core.reconciliation import (
    PositionDiscrepancy,
    ReconciliationReport,
    fetch_exchange_balances,
    reconcile_positions,
)

# -----------------------------------------------------------------------
# PositionDiscrepancy Tests
# -----------------------------------------------------------------------


class TestPositionDiscrepancy:
    """Tests for PositionDiscrepancy dataclass."""

    def test_init_defaults(self):
        """Test default initialization."""
        disc = PositionDiscrepancy()

        assert disc.symbol == ""
        assert disc.internal_quantity == 0.0
        assert disc.exchange_quantity == 0.0
        assert disc.difference == 0.0
        assert disc.difference_pct == 0.0
        assert disc.severity == "info"

    def test_init_with_values(self):
        """Test initialization with values."""
        disc = PositionDiscrepancy(
            symbol="BTCUSD",
            internal_quantity=1.5,
            exchange_quantity=1.4,
            difference=0.1,
            difference_pct=6.67,
            severity="warning",
        )

        assert disc.symbol == "BTCUSD"
        assert disc.internal_quantity == 1.5
        assert disc.exchange_quantity == 1.4
        assert disc.difference == 0.1
        assert disc.difference_pct == 6.67
        assert disc.severity == "warning"

    def test_to_json_produces_valid_json(self):
        """Test to_json() produces valid JSON."""
        disc = PositionDiscrepancy(
            symbol="ETHUSD",
            internal_quantity=10.0,
            exchange_quantity=9.9,
            difference=0.1,
            difference_pct=1.01,
            severity="info",
        )
        json_str = disc.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_to_json_contains_all_fields(self):
        """Test to_json() includes all fields."""
        disc = PositionDiscrepancy(
            symbol="BTCUSD",
            internal_quantity=2.0,
            exchange_quantity=1.8,
            difference=0.2,
            difference_pct=10.0,
            severity="critical",
        )
        json_str = disc.to_json()
        parsed = json.loads(json_str)

        assert parsed["symbol"] == "BTCUSD"
        assert parsed["internal_quantity"] == 2.0
        assert parsed["exchange_quantity"] == 1.8
        assert parsed["difference"] == 0.2
        assert parsed["difference_pct"] == 10.0
        assert parsed["severity"] == "critical"

    def test_to_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        original = PositionDiscrepancy(
            symbol="LTCUSD",
            internal_quantity=5.5,
            exchange_quantity=5.4,
            difference=0.1,
            difference_pct=1.85,
            severity="warning",
        )
        json_str = original.to_json()
        parsed = json.loads(json_str)

        # Reconstruct from parsed JSON
        restored = PositionDiscrepancy(
            symbol=parsed["symbol"],
            internal_quantity=parsed["internal_quantity"],
            exchange_quantity=parsed["exchange_quantity"],
            difference=parsed["difference"],
            difference_pct=parsed["difference_pct"],
            severity=parsed["severity"],
        )

        assert restored.symbol == original.symbol
        assert restored.internal_quantity == original.internal_quantity
        assert restored.exchange_quantity == original.exchange_quantity
        assert restored.difference == original.difference
        assert restored.difference_pct == original.difference_pct
        assert restored.severity == original.severity


# -----------------------------------------------------------------------
# ReconciliationReport Tests
# -----------------------------------------------------------------------


class TestReconciliationReport:
    """Tests for ReconciliationReport dataclass."""

    def test_init_defaults(self):
        """Test default initialization."""
        report = ReconciliationReport()

        assert report.timestamp == 0
        assert report.symbols_checked == 0
        assert report.discrepancies == []
        assert report.exchange_balances == {}
        assert report.internal_positions == {}
        assert report.status == "ok"
        assert report.error is None

    def test_init_with_values(self):
        """Test initialization with values."""
        discs = [
            PositionDiscrepancy(
                symbol="BTCUSD",
                internal_quantity=1.0,
                exchange_quantity=0.9,
                difference=0.1,
                difference_pct=10.0,
                severity="warning",
            )
        ]
        report = ReconciliationReport(
            timestamp=1234567890,
            symbols_checked=1,
            discrepancies=discs,
            exchange_balances={"BTCUSD": 0.9},
            internal_positions={"BTCUSD": 1.0},
            status="warning",
            error=None,
        )

        assert report.timestamp == 1234567890
        assert report.symbols_checked == 1
        assert len(report.discrepancies) == 1
        assert report.exchange_balances == {"BTCUSD": 0.9}
        assert report.internal_positions == {"BTCUSD": 1.0}
        assert report.status == "warning"
        assert report.error is None

    def test_to_json_produces_valid_json(self):
        """Test to_json() produces valid JSON."""
        report = ReconciliationReport(
            timestamp=1000000000,
            symbols_checked=2,
            discrepancies=[],
            exchange_balances={"BTCUSD": 1.0},
            internal_positions={"BTCUSD": 1.0},
            status="ok",
        )
        json_str = report.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_to_json_with_discrepancies(self):
        """Test to_json() with discrepancies."""
        disc = PositionDiscrepancy(
            symbol="BTCUSD",
            internal_quantity=1.0,
            exchange_quantity=0.95,
            difference=0.05,
            difference_pct=5.0,
            severity="warning",
        )
        report = ReconciliationReport(
            timestamp=1234567890,
            symbols_checked=1,
            discrepancies=[disc],
            exchange_balances={"BTCUSD": 0.95},
            internal_positions={"BTCUSD": 1.0},
            status="warning",
        )
        json_str = report.to_json()
        parsed = json.loads(json_str)

        assert parsed["timestamp"] == 1234567890
        assert parsed["symbols_checked"] == 1
        assert len(parsed["discrepancies"]) == 1
        assert parsed["status"] == "warning"

    def test_to_json_with_error(self):
        """Test to_json() with error field."""
        report = ReconciliationReport(
            timestamp=1234567890,
            symbols_checked=0,
            discrepancies=[],
            status="ok",
            error="Failed to fetch exchange data",
        )
        json_str = report.to_json()
        parsed = json.loads(json_str)

        assert parsed["error"] == "Failed to fetch exchange data"


# -----------------------------------------------------------------------
# reconcile_positions() Tests
# -----------------------------------------------------------------------


class TestReconcilePositions:
    """Tests for reconcile_positions() function."""

    def test_matching_positions_no_discrepancies(self):
        """Test matching positions produce no discrepancies."""
        internal = {"BTCUSD": 1.0, "ETHUSD": 10.0}
        exchange = {"BTCUSD": 1.0, "ETHUSD": 10.0}

        report = reconcile_positions(internal, exchange)

        assert report.status == "ok"
        assert len(report.discrepancies) == 0
        assert report.symbols_checked == 2

    def test_small_difference_within_tolerance_info_severity(self):
        """Test small difference within tolerance_pct → info severity."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 1.0005}
        tolerance = 0.01  # 1%

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.status == "ok"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.symbol == "BTCUSD"
        assert disc.severity == "info"
        assert disc.difference_pct == pytest.approx(0.05, abs=0.01)

    def test_medium_difference_warning_severity(self):
        """Test medium difference → warning severity."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 0.95}
        tolerance = 0.01  # 1%

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.status == "warning"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.severity == "warning"
        assert disc.difference_pct == pytest.approx(5.0, abs=0.1)

    def test_large_difference_critical_severity(self):
        """Test large difference → critical severity."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 0.5}
        tolerance = 0.01  # 1%

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.status == "critical"
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.severity == "critical"
        assert disc.difference_pct == pytest.approx(50.0, abs=0.1)

    def test_symbol_only_in_internal(self):
        """Test symbol present in internal but missing from exchange."""
        internal = {"BTCUSD": 1.0, "ETHUSD": 5.0}
        exchange = {"ETHUSD": 5.0}
        tolerance = 0.01

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.symbols_checked == 2
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.symbol == "BTCUSD"
        assert disc.internal_quantity == 1.0
        assert disc.exchange_quantity == 0.0
        assert disc.difference == 1.0

    def test_symbol_only_on_exchange(self):
        """Test symbol present on exchange but missing from internal."""
        internal = {"ETHUSD": 5.0}
        exchange = {"BTCUSD": 2.0, "ETHUSD": 5.0}
        tolerance = 0.01

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.symbols_checked == 2
        assert len(report.discrepancies) == 1
        disc = report.discrepancies[0]
        assert disc.symbol == "BTCUSD"
        assert disc.internal_quantity == 0.0
        assert disc.exchange_quantity == 2.0
        assert disc.difference == -2.0

    def test_multiple_symbols_mixed_severities(self):
        """Test multiple symbols with different severity levels."""
        internal = {
            "BTCUSD": 1.0,  # within tolerance (info)
            "ETHUSD": 10.0,  # warning
            "LTCUSD": 100.0,  # critical
        }
        exchange = {
            "BTCUSD": 1.0005,  # 0.05% diff
            "ETHUSD": 9.5,  # 5% diff
            "LTCUSD": 50.0,  # 50% diff
        }
        tolerance = 0.01

        report = reconcile_positions(internal, exchange, tolerance)

        assert report.status == "critical"
        assert len(report.discrepancies) == 3
        assert report.symbols_checked == 3

        # Sort by symbol for consistent testing
        discs_by_symbol = {d.symbol: d for d in report.discrepancies}

        assert discs_by_symbol["BTCUSD"].severity == "info"
        assert discs_by_symbol["ETHUSD"].severity == "warning"
        assert discs_by_symbol["LTCUSD"].severity == "critical"

    def test_custom_tolerance_pct(self):
        """Test custom tolerance_pct parameter."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 0.95}

        # With strict tolerance (0.01 = 1%)
        report_strict = reconcile_positions(internal, exchange, tolerance_pct=0.01)
        assert report_strict.discrepancies[0].severity == "warning"

        # With lenient tolerance (0.1 = 10%)
        report_lenient = reconcile_positions(internal, exchange, tolerance_pct=0.1)
        assert report_lenient.discrepancies[0].severity == "info"

    def test_difference_calculation_is_absolute(self):
        """Test that difference is internal - exchange (signed, not absolute)."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 0.5}

        report = reconcile_positions(internal, exchange)

        disc = report.discrepancies[0]
        assert disc.difference == 0.5  # internal - exchange = 1.0 - 0.5

    def test_difference_calculation_negative(self):
        """Test difference calculation when exchange > internal."""
        internal = {"BTCUSD": 0.5}
        exchange = {"BTCUSD": 1.0}

        report = reconcile_positions(internal, exchange)

        disc = report.discrepancies[0]
        assert disc.difference == -0.5  # internal - exchange = 0.5 - 1.0

    def test_sorted_discrepancies_by_symbol(self):
        """Test that discrepancies are sorted by symbol."""
        internal = {"ZCUSD": 1.0, "BTCUSD": 2.0, "ETHUSD": 3.0}
        exchange = {}

        report = reconcile_positions(internal, exchange)

        symbols = [d.symbol for d in report.discrepancies]
        assert symbols == ["BTCUSD", "ETHUSD", "ZCUSD"]

    def test_tolerance_boundary_info_vs_warning(self):
        """Test boundary between info and warning severity."""
        tolerance = 0.01
        internal = {"BTCUSD": 1.0}

        # Just below tolerance: should be info
        exchange = {"BTCUSD": 1.0 - (1.0 * tolerance * 0.999)}
        report = reconcile_positions(internal, exchange, tolerance)
        assert report.discrepancies[0].severity == "info"

        # Just above tolerance: should be warning
        exchange = {"BTCUSD": 1.0 - (1.0 * tolerance * 1.001)}
        report = reconcile_positions(internal, exchange, tolerance)
        assert report.discrepancies[0].severity == "warning"

    def test_tolerance_boundary_warning_vs_critical(self):
        """Test boundary between warning and critical severity."""
        tolerance = 0.01
        internal = {"BTCUSD": 1.0}

        # At tolerance * 10 boundary: should be warning
        exchange = {"BTCUSD": 1.0 - (1.0 * tolerance * 10)}
        report = reconcile_positions(internal, exchange, tolerance)
        assert report.discrepancies[0].severity == "warning"

        # Just above tolerance * 10: should be critical
        exchange = {"BTCUSD": 1.0 - (1.0 * tolerance * 10 * 1.001)}
        report = reconcile_positions(internal, exchange, tolerance)
        assert report.discrepancies[0].severity == "critical"

    def test_reference_calculation_uses_max_quantity(self):
        """Test that reference for percentage uses max of internal/exchange."""
        # When internal and exchange differ significantly, reference should be max
        internal = {"BTCUSD": 10.0}
        exchange = {"BTCUSD": 1.0}

        report = reconcile_positions(internal, exchange)

        disc = report.discrepancies[0]
        # diff = |10 - 1| = 9, reference = max(10, 1) = 10
        # diff_pct = 9 / 10 = 0.9 = 90%
        assert disc.difference_pct == pytest.approx(90.0, abs=0.1)

    def test_reference_calculation_minimum_value(self):
        """Test that reference has minimum of 0.0001."""
        # When both are very small/zero, reference should be 0.0001
        internal = {"BTCUSD": 0.00001}
        exchange = {"BTCUSD": 0.0}

        report = reconcile_positions(internal, exchange)

        disc = report.discrepancies[0]
        # diff = |0.00001 - 0| = 0.00001
        # reference = max(0.00001, 0, 0.0001) = 0.0001
        # diff_pct = 0.00001 / 0.0001 = 0.1 = 10%
        assert disc.difference_pct == pytest.approx(10.0, abs=0.1)

    def test_zero_difference_excluded(self):
        """Test that zero differences are not included in discrepancies."""
        internal = {"BTCUSD": 1.0, "ETHUSD": 5.0, "LTCUSD": 0.0}
        exchange = {"BTCUSD": 1.0, "ETHUSD": 5.0, "LTCUSD": 0.0}

        report = reconcile_positions(internal, exchange)

        assert len(report.discrepancies) == 0
        assert report.status == "ok"

    def test_symbols_checked_includes_all_symbols(self):
        """Test symbols_checked includes union of internal and exchange symbols."""
        internal = {"BTCUSD": 1.0, "ETHUSD": 5.0}
        exchange = {"ETHUSD": 5.0, "LTCUSD": 10.0}

        report = reconcile_positions(internal, exchange)

        # Union: BTCUSD, ETHUSD, LTCUSD
        assert report.symbols_checked == 3

    def test_report_contains_input_data(self):
        """Test that report includes original input dicts."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 1.0}

        report = reconcile_positions(internal, exchange)

        assert report.internal_positions == internal
        assert report.exchange_balances == exchange

    def test_empty_positions(self):
        """Test reconciliation with empty positions."""
        internal = {}
        exchange = {}

        report = reconcile_positions(internal, exchange)

        assert report.status == "ok"
        assert report.symbols_checked == 0
        assert len(report.discrepancies) == 0

    def test_timestamp_is_recent(self):
        """Test that report timestamp is set to current time."""
        internal = {"BTCUSD": 1.0}
        exchange = {"BTCUSD": 1.0}

        report = reconcile_positions(internal, exchange)

        # Timestamp should be positive (milliseconds since epoch)
        assert report.timestamp > 0
        assert isinstance(report.timestamp, int)

    def test_worst_severity_escalation(self):
        """Test that worst_severity escalates correctly."""
        internal = {
            "BTCUSD": 1.0,  # info
            "ETHUSD": 10.0,  # warning
        }
        exchange = {
            "BTCUSD": 1.0005,
            "ETHUSD": 9.5,
        }
        tolerance = 0.01

        report = reconcile_positions(internal, exchange, tolerance)

        # Even though we have info + warning, worst should be warning
        assert report.status == "warning"

        # Now add critical
        internal["LTCUSD"] = 100.0
        exchange["LTCUSD"] = 50.0

        report = reconcile_positions(internal, exchange, tolerance)
        assert report.status == "critical"


# -----------------------------------------------------------------------
# fetch_exchange_balances() Tests
# -----------------------------------------------------------------------


class TestFetchExchangeBalances:
    """Tests for fetch_exchange_balances() function."""

    def test_fetch_exchange_balances_basic(self):
        """Test basic fetch with mock client."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.5"},
                },
                {
                    "id": "2",
                    "currency": "ETH",
                    "available_balance": {"value": "10.0"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert balances == {"BTCUSD": 1.5, "ETHUSD": 10.0}

    def test_fetch_exchange_balances_filters_usd(self):
        """Test that USD currency is filtered out."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.5"},
                },
                {
                    "id": "2",
                    "currency": "USD",
                    "available_balance": {"value": "10000.0"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert balances == {"BTCUSD": 1.5}
        assert "USD" not in balances

    def test_fetch_exchange_balances_filters_zero_balance(self):
        """Test that zero balances are filtered out."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.5"},
                },
                {
                    "id": "2",
                    "currency": "ETH",
                    "available_balance": {"value": "0.0"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert balances == {"BTCUSD": 1.5}
        assert "ETHUSD" not in balances

    def test_fetch_exchange_balances_normalizes_format(self):
        """Test that currency is normalized to 'SYMBOLUSD' format."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.0"},
                },
                {
                    "id": "2",
                    "currency": "DOGE",
                    "available_balance": {"value": "100.0"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert "BTCUSD" in balances
        assert "DOGEUSD" in balances
        assert "BTC" not in balances
        assert "DOGE" not in balances

    def test_fetch_exchange_balances_parses_string_values(self):
        """Test that string balance values are converted to float."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.23456789"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert isinstance(balances["BTCUSD"], float)
        assert balances["BTCUSD"] == pytest.approx(1.23456789)

    def test_fetch_exchange_balances_handles_empty_accounts(self):
        """Test handling of empty accounts list."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {"accounts": []}

        balances = fetch_exchange_balances(mock_client)

        assert balances == {}

    def test_fetch_exchange_balances_handles_missing_accounts_key(self):
        """Test handling of missing 'accounts' key."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {}

        balances = fetch_exchange_balances(mock_client)

        assert balances == {}

    def test_fetch_exchange_balances_handles_missing_currency(self):
        """Test handling of account without currency field."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    # Missing currency field
                    "available_balance": {"value": "1.5"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        # Empty currency becomes "" which becomes "USD" after formatting, which is filtered out
        # Actually, empty string + "USD" = "USD", so it will be included but then filtered
        assert balances == {"USD": 1.5}

    def test_fetch_exchange_balances_handles_missing_available_balance(self):
        """Test handling of account without available_balance."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    # Missing available_balance field
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        # Missing available_balance should default to 0, which is filtered out
        assert balances == {}

    def test_fetch_exchange_balances_handles_malformed_balance_value(self):
        """Test handling of malformed balance value."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {},  # Missing 'value' key
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        # Missing value should default to 0.0
        assert balances == {}

    def test_fetch_exchange_balances_exception_returns_empty_dict(self):
        """Test that exceptions are caught and empty dict is returned."""
        mock_client = MagicMock()
        mock_client.get_accounts.side_effect = Exception("API Error")

        balances = fetch_exchange_balances(mock_client)

        assert balances == {}

    def test_fetch_exchange_balances_connection_error(self):
        """Test handling of connection errors."""
        mock_client = MagicMock()
        mock_client.get_accounts.side_effect = ConnectionError("Network error")

        balances = fetch_exchange_balances(mock_client)

        assert balances == {}

    def test_fetch_exchange_balances_timeout_error(self):
        """Test handling of timeout errors."""
        mock_client = MagicMock()
        mock_client.get_accounts.side_effect = TimeoutError("Request timeout")

        balances = fetch_exchange_balances(mock_client)

        assert balances == {}

    def test_fetch_exchange_balances_multiple_accounts(self):
        """Test with multiple accounts of different cryptocurrencies."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.5"},
                },
                {
                    "id": "2",
                    "currency": "ETH",
                    "available_balance": {"value": "10.0"},
                },
                {
                    "id": "3",
                    "currency": "LTC",
                    "available_balance": {"value": "50.5"},
                },
                {
                    "id": "4",
                    "currency": "USD",
                    "available_balance": {"value": "50000.0"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert len(balances) == 3
        assert balances["BTCUSD"] == 1.5
        assert balances["ETHUSD"] == 10.0
        assert balances["LTCUSD"] == 50.5

    def test_fetch_exchange_balances_with_scientific_notation(self):
        """Test parsing balance values in scientific notation."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "1.5e-2"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        assert balances["BTCUSD"] == pytest.approx(0.015)

    def test_fetch_exchange_balances_with_negative_balance(self):
        """Test that negative balances are treated as non-zero (not filtered)."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {
                    "id": "1",
                    "currency": "BTC",
                    "available_balance": {"value": "-1.5"},
                },
            ]
        }

        balances = fetch_exchange_balances(mock_client)

        # Negative balance is non-zero, so should be included
        assert "BTCUSD" in balances
        assert balances["BTCUSD"] == pytest.approx(-1.5)


# -----------------------------------------------------------------------
# Integration Tests
# -----------------------------------------------------------------------


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_reconcile_with_fetched_balances(self):
        """Test reconcile_positions with balances from fetch_exchange_balances."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {"currency": "BTC", "available_balance": {"value": "1.0"}},
                {"currency": "ETH", "available_balance": {"value": "10.0"}},
            ]
        }

        balances = fetch_exchange_balances(mock_client)
        internal = {"BTCUSD": 1.0, "ETHUSD": 10.0}

        report = reconcile_positions(internal, balances)

        assert report.status == "ok"
        assert len(report.discrepancies) == 0

    def test_reconcile_with_mismatched_fetched_balances(self):
        """Test reconcile_positions detecting mismatches with fetched balances."""
        mock_client = MagicMock()
        mock_client.get_accounts.return_value = {
            "accounts": [
                {"currency": "BTC", "available_balance": {"value": "0.95"}},
            ]
        }

        balances = fetch_exchange_balances(mock_client)
        internal = {"BTCUSD": 1.0}

        report = reconcile_positions(internal, balances, tolerance_pct=0.01)

        assert report.status == "warning"
        assert len(report.discrepancies) == 1
