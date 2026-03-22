"""Tests for backtest_svc.results — file-based result storage."""

from __future__ import annotations

import pytest

from backtest_svc.replay import BacktestConfig, ReplayStats
from backtest_svc.results import BacktestResultStore


@pytest.fixture
def store(tmp_path) -> BacktestResultStore:
    return BacktestResultStore(results_dir=str(tmp_path))


@pytest.fixture
def sample_stats() -> ReplayStats:
    return ReplayStats(
        backtest_id="bt-test-123",
        trades_replayed=1000,
        depth_updates_replayed=500,
        duration_seconds=5.0,
        data_span_seconds=3600.0,
        messages_per_second=300.0,
    )


@pytest.fixture
def sample_config() -> BacktestConfig:
    return BacktestConfig(
        backtest_id="bt-test-123",
        symbol="BTCUSD",
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T12:00:00",
    )


class TestSaveAndGet:
    def test_save_creates_file(self, store: BacktestResultStore, sample_stats, sample_config):
        store.save(sample_stats, sample_config)
        result = store.get("bt-test-123")
        assert result is not None
        assert result["backtest_id"] == "bt-test-123"
        assert result["trades_replayed"] == 1000

    def test_get_nonexistent_returns_none(self, store: BacktestResultStore):
        assert store.get("nonexistent") is None

    def test_save_includes_all_fields(self, store: BacktestResultStore, sample_stats, sample_config):
        store.save(sample_stats, sample_config)
        result = store.get("bt-test-123")
        assert result["symbol"] == "BTCUSD"
        assert result["start_time"] == "2026-01-01T00:00:00"
        assert result["end_time"] == "2026-01-01T12:00:00"
        assert result["duration_seconds"] == 5.0
        assert result["messages_per_second"] == 300.0
        assert "timestamp" in result


class TestListAll:
    def test_empty_list(self, store: BacktestResultStore):
        assert store.list_all() == []

    def test_lists_all_runs(self, store: BacktestResultStore, sample_config):
        for i in range(3):
            stats = ReplayStats(backtest_id=f"bt-{i}", trades_replayed=i * 100)
            config = BacktestConfig(
                backtest_id=f"bt-{i}", symbol="BTCUSD", start_time="2026-01-01", end_time="2026-01-02"
            )
            store.save(stats, config)

        results = store.list_all()
        assert len(results) == 3

    def test_sorted_newest_first(self, store: BacktestResultStore):
        import time

        for i in range(3):
            stats = ReplayStats(backtest_id=f"bt-{i}")
            config = BacktestConfig(
                backtest_id=f"bt-{i}", symbol="BTCUSD", start_time="2026-01-01", end_time="2026-01-02"
            )
            store.save(stats, config)
            time.sleep(0.01)

        results = store.list_all()
        # Newest (bt-2) should be first
        assert results[0]["backtest_id"] == "bt-2"


class TestDelete:
    def test_delete_existing(self, store: BacktestResultStore, sample_stats, sample_config):
        store.save(sample_stats, sample_config)
        assert store.delete("bt-test-123") is True
        assert store.get("bt-test-123") is None

    def test_delete_nonexistent(self, store: BacktestResultStore):
        assert store.delete("nonexistent") is False
