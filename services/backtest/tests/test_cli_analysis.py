"""Tests for CLI analysis commands — unit tests for helpers and integration tests for commands."""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

from backtest_svc.cli_analysis import (
    _generate_sample_trades,
    _load_equity,
    _load_trades,
)

# Modules using StrEnum (param_sensitivity, walk_forward, validation) require Python 3.11+
_needs_311 = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="StrEnum requires Python 3.11+",
)

# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestLoadTrades:
    def test_load_from_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"symbol": "BTCUSD", "price": 50000}\n')
            f.write('{"symbol": "BTCUSD", "price": 51000}\n')
            f.write("\n")  # blank line should be skipped
            path = f.name

        try:
            trades = _load_trades(path)
            assert len(trades) == 2
            assert trades[0]["price"] == 50000
            assert trades[1]["price"] == 51000
        finally:
            os.unlink(path)

    def test_load_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            path = f.name

        try:
            trades = _load_trades(path)
            assert trades == []
        finally:
            os.unlink(path)


class TestLoadEquity:
    def test_load_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([100000, 100100, 100050, 100200], f)
            path = f.name

        try:
            equity = _load_equity(path)
            assert len(equity) == 4
            assert equity[0] == 100000.0
        finally:
            os.unlink(path)

    def test_load_dict_format(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"equity_curve": [100000, 100500, 101000]}, f)
            path = f.name

        try:
            equity = _load_equity(path)
            assert len(equity) == 3
            assert equity[-1] == 101000.0
        finally:
            os.unlink(path)

    def test_load_unknown_format(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"foo": "bar"}, f)
            path = f.name

        try:
            equity = _load_equity(path)
            assert equity == []
        finally:
            os.unlink(path)


class TestGenerateSampleTrades:
    def test_default_count(self):
        trades = _generate_sample_trades()
        assert len(trades) == 500

    def test_custom_count(self):
        trades = _generate_sample_trades(n=100)
        assert len(trades) == 100

    def test_symbol_set(self):
        trades = _generate_sample_trades(symbol="ETHUSD", n=10)
        assert all(t["symbol"] == "ETHUSD" for t in trades)

    def test_trade_fields(self):
        trades = _generate_sample_trades(n=5)
        for t in trades:
            assert "symbol" in t
            assert "price" in t
            assert "quantity" in t
            assert "timestamp_exchange" in t
            assert t["price"] > 0
            assert t["quantity"] > 0

    def test_reproducible(self):
        t1 = _generate_sample_trades(n=50)
        t2 = _generate_sample_trades(n=50)
        assert t1 == t2  # same seed=42 inside


# ---------------------------------------------------------------------------
# Integration tests for CLI commands (using synthetic data)
# ---------------------------------------------------------------------------


@_needs_311
class TestCmdSensitivity:
    def test_runs_without_error(self, capsys):
        """Sensitivity command should run to completion with synthetic data."""
        import argparse

        from backtest_svc.cli_analysis import cmd_sensitivity

        args = argparse.Namespace(
            trades=None,
            symbol="BTCUSD",
            strategy="mean_reversion",
            output=None,
            num_trades=200,
            seed=42,
            random=False,
            random_samples=10,
            fee_rate=0.006,
            slippage_bps=1.0,
        )
        cmd_sensitivity(args)
        captured = capsys.readouterr()
        assert "Parameter Sensitivity Analysis" in captured.out
        assert "Best Sharpe" in captured.out

    def test_writes_output_json(self):
        import argparse

        from backtest_svc.cli_analysis import cmd_sensitivity

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name

        try:
            args = argparse.Namespace(
                trades=None,
                symbol="BTCUSD",
                strategy="mean_reversion",
                output=output_path,
                num_trades=200,
                seed=42,
                random=False,
                random_samples=10,
                fee_rate=0.006,
                slippage_bps=1.0,
            )
            cmd_sensitivity(args)
            with open(output_path) as f:
                data = json.load(f)
            assert "best_params" in data
            assert "best_sharpe" in data
        finally:
            os.unlink(output_path)


class TestCmdMonteCarlo:
    def test_runs_with_equity_file(self, capsys):
        import argparse

        from backtest_svc.cli_analysis import cmd_monte_carlo

        # Write a simple equity curve
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            equity = [100000 + i * 10 for i in range(100)]
            json.dump(equity, f)
            eq_path = f.name

        try:
            args = argparse.Namespace(
                equity=eq_path,
                trades=None,
                symbol="BTCUSD",
                strategy="mean_reversion",
                output=None,
                num_trades=200,
                seed=42,
                simulations=50,
                block_size=1,
            )
            cmd_monte_carlo(args)
            captured = capsys.readouterr()
            assert "Monte Carlo Simulation" in captured.out
            assert "P(Sharpe > 0)" in captured.out
        finally:
            os.unlink(eq_path)


@_needs_311
class TestCmdCostSweep:
    def test_runs_without_error(self, capsys):
        import argparse

        from backtest_svc.cli_analysis import cmd_cost_sweep

        args = argparse.Namespace(
            trades=None,
            symbol="BTCUSD",
            strategy="mean_reversion",
            output=None,
            num_trades=200,
            seed=42,
            dimensions="fee_rate,slippage_bps",
        )
        cmd_cost_sweep(args)
        captured = capsys.readouterr()
        assert "Sensitivity Sweep" in captured.out


@_needs_311
class TestCmdUnknownStrategy:
    def test_unknown_strategy_exits_gracefully(self, capsys):
        import argparse

        from backtest_svc.cli_analysis import cmd_sensitivity

        args = argparse.Namespace(
            trades=None,
            symbol="BTCUSD",
            strategy="exotic_strategy",
            output=None,
            num_trades=200,
            seed=42,
            random=False,
            random_samples=10,
            fee_rate=0.006,
            slippage_bps=1.0,
        )
        cmd_sensitivity(args)
        captured = capsys.readouterr()
        assert "Unknown strategy" in captured.out
