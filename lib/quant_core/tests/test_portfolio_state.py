"""Tests for quant_core.portfolio_state — Redis-backed portfolio state."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant_core.portfolio_state import (
    INITIAL_EQUITY,
    read_portfolio_from_redis,
    sync_portfolio_to_redis,
)
from quant_core.redis_utils import Keys


class TestSyncPortfolioToRedis:
    """Tests for sync_portfolio_to_redis() function."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client with pipeline support."""
        mock = MagicMock()
        mock.pipeline.return_value = MagicMock()
        return mock

    def test_sync_portfolio_calls_pipeline(self, mock_redis):
        """sync_portfolio_to_redis calls r.pipeline()."""
        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions={},
            current_equity=100000.0,
            peak_equity=100000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=0.0,
        )

        mock_redis.pipeline.assert_called_once()

    def test_sync_portfolio_hsets_portfolio_summary(self, mock_redis):
        """sync_portfolio_to_redis writes portfolio summary to portfolio key."""
        mock_pipe = mock_redis.pipeline.return_value

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions={},
            current_equity=101500.0,
            peak_equity=102000.0,
            realized_pnl=1500.0,
            unrealized_pnl=200.0,
            total_fees=50.0,
        )

        # Verify first hset call (portfolio summary)
        calls = mock_pipe.hset.call_args_list
        assert len(calls) >= 1

        portfolio_call = calls[0]
        assert portfolio_call[0][0] == Keys.portfolio("test-run")
        mapping = portfolio_call[1]["mapping"]

        assert mapping["current_equity"] == "101500.0"
        assert mapping["peak_equity"] == "102000.0"
        assert mapping["realized_pnl"] == "1500.0"
        assert mapping["unrealized_pnl"] == "200.0"
        assert mapping["total_fees"] == "50.0"

    def test_sync_portfolio_hsets_position_keys(self, mock_redis):
        """sync_portfolio_to_redis writes per-symbol position keys."""
        mock_pipe = mock_redis.pipeline.return_value

        positions = {
            "BTCUSD": {
                "quantity": 0.5,
                "avg_entry_price": 40000.0,
                "realized_pnl": 1000.0,
                "unrealized_pnl": 500.0,
            },
            "ETHUSD": {
                "quantity": 5.0,
                "avg_entry_price": 2000.0,
                "realized_pnl": 2000.0,
                "unrealized_pnl": -300.0,
            },
        }

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions=positions,
            current_equity=103500.0,
            peak_equity=104000.0,
            realized_pnl=3000.0,
            unrealized_pnl=200.0,
            total_fees=100.0,
        )

        calls = mock_pipe.hset.call_args_list
        # First call is portfolio summary, next two are position keys
        assert len(calls) >= 3

        # Check BTCUSD position
        btc_call = calls[1]
        assert btc_call[0][0] == Keys.position("test-run", "BTCUSD")
        btc_mapping = btc_call[1]["mapping"]
        assert btc_mapping["quantity"] == "0.5"
        assert btc_mapping["avg_entry_price"] == "40000.0"
        assert btc_mapping["realized_pnl"] == "1000.0"
        assert btc_mapping["unrealized_pnl"] == "500.0"

        # Check ETHUSD position
        eth_call = calls[2]
        assert eth_call[0][0] == Keys.position("test-run", "ETHUSD")
        eth_mapping = eth_call[1]["mapping"]
        assert eth_mapping["quantity"] == "5.0"
        assert eth_mapping["avg_entry_price"] == "2000.0"
        assert eth_mapping["realized_pnl"] == "2000.0"
        assert eth_mapping["unrealized_pnl"] == "-300.0"

    def test_sync_portfolio_executes_pipeline(self, mock_redis):
        """sync_portfolio_to_redis calls pipeline.execute()."""
        mock_pipe = mock_redis.pipeline.return_value

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions={},
            current_equity=100000.0,
            peak_equity=100000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=0.0,
        )

        mock_pipe.execute.assert_called_once()

    def test_sync_portfolio_handles_missing_position_fields(self, mock_redis):
        """sync_portfolio_to_redis uses 0.0 defaults for missing position fields."""
        mock_pipe = mock_redis.pipeline.return_value

        positions = {
            "BTCUSD": {
                "quantity": 1.0,
                # Missing avg_entry_price, realized_pnl, unrealized_pnl
            },
        }

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions=positions,
            current_equity=100000.0,
            peak_equity=100000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=0.0,
        )

        calls = mock_pipe.hset.call_args_list
        position_call = calls[1]
        mapping = position_call[1]["mapping"]

        assert mapping["quantity"] == "1.0"
        assert mapping["avg_entry_price"] == "0.0"
        assert mapping["realized_pnl"] == "0.0"
        assert mapping["unrealized_pnl"] == "0.0"

    def test_sync_portfolio_with_empty_positions(self, mock_redis):
        """sync_portfolio_to_redis works with no positions."""
        mock_pipe = mock_redis.pipeline.return_value

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions={},
            current_equity=100000.0,
            peak_equity=100000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=0.0,
        )

        calls = mock_pipe.hset.call_args_list
        # Should only have portfolio summary, no position keys
        assert len(calls) == 1

    def test_sync_portfolio_converts_floats_to_strings(self, mock_redis):
        """sync_portfolio_to_redis converts all numeric values to strings."""
        mock_pipe = mock_redis.pipeline.return_value

        sync_portfolio_to_redis(
            mock_redis,
            run_id="test-run",
            positions={
                "BTCUSD": {
                    "quantity": 0.5,
                    "avg_entry_price": 40000.5,
                    "realized_pnl": 1000.25,
                    "unrealized_pnl": -500.75,
                }
            },
            current_equity=101234.56,
            peak_equity=102000.99,
            realized_pnl=1234.56,
            unrealized_pnl=-765.43,
            total_fees=25.5,
        )

        # Check portfolio summary
        portfolio_call = mock_pipe.hset.call_args_list[0]
        mapping = portfolio_call[1]["mapping"]
        assert isinstance(mapping["current_equity"], str)
        assert isinstance(mapping["peak_equity"], str)
        assert isinstance(mapping["realized_pnl"], str)
        assert isinstance(mapping["unrealized_pnl"], str)
        assert isinstance(mapping["total_fees"], str)

        # Check position
        position_call = mock_pipe.hset.call_args_list[1]
        mapping = position_call[1]["mapping"]
        assert isinstance(mapping["quantity"], str)
        assert isinstance(mapping["avg_entry_price"], str)
        assert isinstance(mapping["realized_pnl"], str)
        assert isinstance(mapping["unrealized_pnl"], str)


class TestReadPortfolioFromRedis:
    """Tests for read_portfolio_from_redis() function."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    def test_read_portfolio_returns_defaults_when_no_data(self, mock_redis):
        """read_portfolio_from_redis returns defaults if portfolio key doesn't exist."""
        mock_redis.hgetall.return_value = {}

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert result["positions"] == {}
        assert result["current_equity"] == INITIAL_EQUITY
        assert result["peak_equity"] == INITIAL_EQUITY
        assert result["realized_pnl"] == 0.0
        assert result["unrealized_pnl"] == 0.0

    def test_read_portfolio_calls_hgetall_for_summary(self, mock_redis):
        """read_portfolio_from_redis reads portfolio summary from Redis."""
        mock_redis.hgetall.return_value = {}

        read_portfolio_from_redis(mock_redis, run_id="test-run")

        mock_redis.hgetall.assert_called()
        assert Keys.portfolio("test-run") in str(mock_redis.hgetall.call_args)

    def test_read_portfolio_parses_stored_data(self, mock_redis):
        """read_portfolio_from_redis correctly parses stored portfolio data."""
        # Mock the summary read
        mock_redis.hgetall.return_value = {
            "current_equity": "101500.0",
            "peak_equity": "102000.0",
            "realized_pnl": "1500.0",
            "unrealized_pnl": "200.0",
        }
        # No positions
        mock_redis.scan.return_value = (0, [])

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert result["current_equity"] == 101500.0
        assert result["peak_equity"] == 102000.0
        assert result["realized_pnl"] == 1500.0
        assert result["unrealized_pnl"] == 200.0

    def test_read_portfolio_with_specific_symbols(self, mock_redis):
        """read_portfolio_from_redis reads only specified symbols."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},  # BTCUSD
            {"quantity": "5.0", "avg_entry_price": "2000.0"},  # ETHUSD
        ]

        result = read_portfolio_from_redis(
            mock_redis,
            run_id="test-run",
            symbols=["BTCUSD", "ETHUSD"],
        )

        assert "BTCUSD" in result["positions"]
        assert "ETHUSD" in result["positions"]
        assert result["positions"]["BTCUSD"] == 0.5
        assert result["positions"]["ETHUSD"] == 5.0

    def test_read_portfolio_with_symbols_reads_only_those_keys(self, mock_redis):
        """read_portfolio_from_redis with symbols list does not call scan."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "1.0", "avg_entry_price": "30000.0"},
        ]

        read_portfolio_from_redis(
            mock_redis,
            run_id="test-run",
            symbols=["BTCUSD"],
        )

        # scan should not be called when symbols list is provided
        mock_redis.scan.assert_not_called()

    def test_read_portfolio_without_symbols_uses_scan(self, mock_redis):
        """read_portfolio_from_redis without symbols does a scan for all position keys."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},
            {"quantity": "5.0", "avg_entry_price": "2000.0"},
        ]
        # scan returns keys (as strings for decode_responses=True) on first iteration, then 0 cursor to stop
        mock_redis.scan.return_value = (
            0,
            [
                "positions:test-run:BTCUSD",
                "positions:test-run:ETHUSD",
            ],
        )

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        mock_redis.scan.assert_called_once()
        assert "BTCUSD" in result["positions"]
        assert "ETHUSD" in result["positions"]

    def test_read_portfolio_scan_pagination(self, mock_redis):
        """read_portfolio_from_redis handles paginated scan results."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},  # Page 1
            {"quantity": "5.0", "avg_entry_price": "2000.0"},  # Page 2
        ]
        # First scan call returns cursor 42, second returns 0 (done)
        mock_redis.scan.side_effect = [
            (42, ["positions:test-run:BTCUSD"]),
            (0, ["positions:test-run:ETHUSD"]),
        ]

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert mock_redis.scan.call_count == 2
        assert "BTCUSD" in result["positions"]
        assert "ETHUSD" in result["positions"]

    def test_read_portfolio_excludes_zero_quantity_with_symbols(self, mock_redis):
        """read_portfolio_from_redis excludes zero-quantity positions with symbols."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},  # BTCUSD
            {"quantity": "0.0", "avg_entry_price": "2000.0"},  # ETHUSD (zero)
        ]

        result = read_portfolio_from_redis(
            mock_redis,
            run_id="test-run",
            symbols=["BTCUSD", "ETHUSD"],
        )

        assert "BTCUSD" in result["positions"]
        assert "ETHUSD" not in result["positions"]

    def test_read_portfolio_excludes_zero_quantity_without_symbols(self, mock_redis):
        """read_portfolio_from_redis excludes zero-quantity positions without symbols."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},  # BTCUSD
            {"quantity": "0.0", "avg_entry_price": "2000.0"},  # ETHUSD (zero)
        ]
        mock_redis.scan.return_value = (
            0,
            [
                "positions:test-run:BTCUSD",
                "positions:test-run:ETHUSD",
            ],
        )

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert "BTCUSD" in result["positions"]
        assert "ETHUSD" not in result["positions"]

    def test_read_portfolio_handles_empty_position_data(self, mock_redis):
        """read_portfolio_from_redis skips position keys with no data."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {},  # Empty position data
        ]

        result = read_portfolio_from_redis(
            mock_redis,
            run_id="test-run",
            symbols=["BTCUSD"],
        )

        assert result["positions"] == {}

    def test_read_portfolio_uppercases_symbol_keys(self, mock_redis):
        """read_portfolio_from_redis converts symbol keys to uppercase."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},
        ]

        result = read_portfolio_from_redis(
            mock_redis,
            run_id="test-run",
            symbols=["btcusd"],  # lowercase input
        )

        assert "BTCUSD" in result["positions"]
        assert "btcusd" not in result["positions"]

    def test_read_portfolio_extracts_symbol_from_scan_key(self, mock_redis):
        """read_portfolio_from_redis extracts symbol from positions:{run_id}:{symbol} key."""
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": "100000.0",
                "peak_equity": "100000.0",
                "realized_pnl": "0.0",
                "unrealized_pnl": "0.0",
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},
        ]
        # Verify that scan keys are parsed correctly
        mock_redis.scan.return_value = (0, ["positions:test-run:BTCUSD"])

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert "BTCUSD" in result["positions"]

    def test_read_portfolio_handles_partial_summary_data(self, mock_redis):
        """read_portfolio_from_redis uses defaults for missing summary fields."""
        mock_redis.hgetall.return_value = {
            "current_equity": "101000.0",
            # Missing peak_equity, realized_pnl, unrealized_pnl
        }
        mock_redis.scan.return_value = (0, [])

        result = read_portfolio_from_redis(mock_redis, run_id="test-run")

        assert result["current_equity"] == 101000.0
        assert result["peak_equity"] == INITIAL_EQUITY
        assert result["realized_pnl"] == 0.0
        assert result["unrealized_pnl"] == 0.0


class TestRoundTrip:
    """Tests for round-trip consistency: write then read."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        return MagicMock()

    def test_round_trip_with_single_position(self, mock_redis):
        """Round-trip write and read returns consistent data."""
        run_id = "test-run"
        positions = {
            "BTCUSD": {
                "quantity": 0.5,
                "avg_entry_price": 40000.0,
                "realized_pnl": 1000.0,
                "unrealized_pnl": 500.0,
            }
        }
        current_equity = 101500.0
        peak_equity = 102000.0
        realized_pnl = 1000.0
        unrealized_pnl = 500.0
        total_fees = 50.0

        # Write
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        sync_portfolio_to_redis(
            mock_redis,
            run_id=run_id,
            positions=positions,
            current_equity=current_equity,
            peak_equity=peak_equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_fees=total_fees,
        )

        # Simulate what was written by setting up the read mocks
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": str(current_equity),
                "peak_equity": str(peak_equity),
                "realized_pnl": str(realized_pnl),
                "unrealized_pnl": str(unrealized_pnl),
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},
        ]

        # Read
        result = read_portfolio_from_redis(
            mock_redis,
            run_id=run_id,
            symbols=["BTCUSD"],
        )

        assert result["current_equity"] == current_equity
        assert result["peak_equity"] == peak_equity
        assert result["realized_pnl"] == realized_pnl
        assert result["unrealized_pnl"] == unrealized_pnl
        assert result["positions"]["BTCUSD"] == 0.5

    def test_round_trip_with_multiple_positions(self, mock_redis):
        """Round-trip with multiple positions."""
        run_id = "test-run"
        positions = {
            "BTCUSD": {
                "quantity": 0.5,
                "avg_entry_price": 40000.0,
                "realized_pnl": 1000.0,
                "unrealized_pnl": 500.0,
            },
            "ETHUSD": {
                "quantity": 5.0,
                "avg_entry_price": 2000.0,
                "realized_pnl": 2000.0,
                "unrealized_pnl": -300.0,
            },
        }
        current_equity = 103500.0
        peak_equity = 104000.0
        realized_pnl = 3000.0
        unrealized_pnl = 200.0
        total_fees = 100.0

        # Write
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        sync_portfolio_to_redis(
            mock_redis,
            run_id=run_id,
            positions=positions,
            current_equity=current_equity,
            peak_equity=peak_equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_fees=total_fees,
        )

        # Simulate read
        mock_redis.hgetall.side_effect = [
            {
                "current_equity": str(current_equity),
                "peak_equity": str(peak_equity),
                "realized_pnl": str(realized_pnl),
                "unrealized_pnl": str(unrealized_pnl),
            },
            {"quantity": "0.5", "avg_entry_price": "40000.0"},
            {"quantity": "5.0", "avg_entry_price": "2000.0"},
        ]

        # Read
        result = read_portfolio_from_redis(
            mock_redis,
            run_id=run_id,
            symbols=["BTCUSD", "ETHUSD"],
        )

        assert result["current_equity"] == current_equity
        assert result["peak_equity"] == peak_equity
        assert result["realized_pnl"] == realized_pnl
        assert result["unrealized_pnl"] == unrealized_pnl
        assert len(result["positions"]) == 2
        assert result["positions"]["BTCUSD"] == 0.5
        assert result["positions"]["ETHUSD"] == 5.0

    def test_round_trip_empty_portfolio(self, mock_redis):
        """Round-trip with no positions."""
        run_id = "test-run"

        # Write empty portfolio
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        sync_portfolio_to_redis(
            mock_redis,
            run_id=run_id,
            positions={},
            current_equity=INITIAL_EQUITY,
            peak_equity=INITIAL_EQUITY,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_fees=0.0,
        )

        # Simulate read
        mock_redis.hgetall.return_value = {
            "current_equity": str(INITIAL_EQUITY),
            "peak_equity": str(INITIAL_EQUITY),
            "realized_pnl": "0.0",
            "unrealized_pnl": "0.0",
        }
        mock_redis.scan.return_value = (0, [])

        # Read
        result = read_portfolio_from_redis(mock_redis, run_id=run_id)

        assert result["positions"] == {}
        assert result["current_equity"] == INITIAL_EQUITY
        assert result["peak_equity"] == INITIAL_EQUITY
