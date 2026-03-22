"""Tests for backtest comparison."""

from __future__ import annotations

import pytest

from backtest_svc.comparison import (
    ComparisonResult,
    RunMetrics,
    compare_pair,
    compare_runs,
    load_run_metrics,
)
from backtest_svc.replay import BacktestConfig, ReplayStats
from backtest_svc.results import BacktestResultStore


@pytest.fixture
def store(tmp_path) -> BacktestResultStore:
    return BacktestResultStore(results_dir=str(tmp_path))


def _save_run(store, bt_id, trades=100, sharpe=1.0, total_return=0.05):
    """Helper to save a run with extended metrics."""
    stats = ReplayStats(
        backtest_id=bt_id,
        trades_replayed=trades,
        duration_seconds=5.0,
        messages_per_second=20.0,
    )
    config = BacktestConfig(
        backtest_id=bt_id,
        symbol="BTCUSD",
        start_time="2026-01-01",
        end_time="2026-01-02",
    )
    store.save(stats, config)

    # Patch in extended metrics (normally added by post-trade)
    import json

    filepath = store._dir / f"{bt_id}.json"
    data = json.loads(filepath.read_text())
    data["sharpe"] = sharpe
    data["total_return"] = total_return
    data["max_drawdown"] = 0.05
    data["win_rate"] = 0.55
    data["profit_factor"] = 1.5
    filepath.write_text(json.dumps(data))


class TestLoadRunMetrics:
    def test_load_all(self, store):
        _save_run(store, "bt-1")
        _save_run(store, "bt-2")

        metrics = load_run_metrics(store)
        assert len(metrics) == 2

    def test_load_specific(self, store):
        _save_run(store, "bt-1")
        _save_run(store, "bt-2")
        _save_run(store, "bt-3")

        metrics = load_run_metrics(store, ["bt-1", "bt-3"])
        assert len(metrics) == 2
        ids = {m.backtest_id for m in metrics}
        assert ids == {"bt-1", "bt-3"}

    def test_load_nonexistent(self, store):
        metrics = load_run_metrics(store, ["nonexistent"])
        assert metrics == []

    def test_metrics_populated(self, store):
        _save_run(store, "bt-1", sharpe=2.5, total_return=0.15)
        metrics = load_run_metrics(store, ["bt-1"])
        assert len(metrics) == 1
        assert metrics[0].sharpe == 2.5
        assert metrics[0].total_return == 0.15


class TestComparePair:
    def test_basic_comparison(self):
        a = RunMetrics(backtest_id="bt-a", sharpe=1.5, total_return=0.10)
        b = RunMetrics(backtest_id="bt-b", sharpe=2.0, total_return=0.15)

        result = compare_pair(a, b)

        assert result.run_a_id == "bt-a"
        assert result.run_b_id == "bt-b"
        assert result.better_run == "bt-b"
        assert len(result.deltas) == 7

    def test_deltas_correct(self):
        a = RunMetrics(backtest_id="bt-a", sharpe=1.0)
        b = RunMetrics(backtest_id="bt-b", sharpe=2.0)

        result = compare_pair(a, b)

        sharpe_delta = next(d for d in result.deltas if d.metric_name == "sharpe")
        assert sharpe_delta.absolute_delta == 1.0
        assert sharpe_delta.pct_change == 100.0

    def test_equal_runs(self):
        a = RunMetrics(backtest_id="bt-a", sharpe=1.0)
        b = RunMetrics(backtest_id="bt-b", sharpe=1.0)

        result = compare_pair(a, b)
        assert result.better_run == "bt-a"  # tie goes to a


class TestCompareRuns:
    def test_full_comparison(self, store):
        _save_run(store, "bt-1", sharpe=1.0)
        _save_run(store, "bt-2", sharpe=2.0)
        _save_run(store, "bt-3", sharpe=1.5)

        result = compare_runs(store)

        assert isinstance(result, ComparisonResult)
        assert len(result.runs) == 3
        assert result.ranked_by_sharpe[0] == "bt-2"
        # 3 runs → 3 pairwise comparisons
        assert len(result.pairwise) == 3

    def test_empty_store(self, store):
        result = compare_runs(store)
        assert result.runs == []

    def test_single_run(self, store):
        _save_run(store, "bt-1")
        result = compare_runs(store)
        assert len(result.runs) == 1
        assert len(result.pairwise) == 0

    def test_specific_ids(self, store):
        _save_run(store, "bt-1", sharpe=1.0)
        _save_run(store, "bt-2", sharpe=2.0)
        _save_run(store, "bt-3", sharpe=3.0)

        result = compare_runs(store, ["bt-1", "bt-3"])
        assert len(result.runs) == 2
        assert len(result.pairwise) == 1
