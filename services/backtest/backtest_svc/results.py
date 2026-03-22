"""Backtest result storage.

Stores backtest run metadata and stats as JSON files in a local directory.
Simple file-based storage — no database dependency for the CLI.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_RESULTS_DIR = os.getenv("BACKTEST_RESULTS_DIR", ".backtest_results")


class BacktestResultStore:
    """File-based storage for backtest run results."""

    def __init__(self, results_dir: str = DEFAULT_RESULTS_DIR):
        self._dir = Path(results_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, stats, config) -> None:
        """Save a backtest run's stats and config."""
        data = {
            "backtest_id": stats.backtest_id,
            "symbol": config.symbol,
            "start_time": config.start_time,
            "end_time": config.end_time,
            "replay_speed": config.replay_speed,
            "speed_multiplier": config.speed_multiplier,
            "trades_replayed": stats.trades_replayed,
            "depth_updates_replayed": stats.depth_updates_replayed,
            "duration_seconds": stats.duration_seconds,
            "data_span_seconds": stats.data_span_seconds,
            "messages_per_second": stats.messages_per_second,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        filepath = self._dir / f"{stats.backtest_id}.json"
        filepath.write_text(json.dumps(data, indent=2))
        logger.info("Saved results to %s", filepath)

    def get(self, backtest_id: str) -> dict | None:
        """Retrieve results for a specific backtest run."""
        filepath = self._dir / f"{backtest_id}.json"
        if not filepath.exists():
            return None
        return json.loads(filepath.read_text())

    def list_all(self) -> list[dict]:
        """List all stored backtest runs, newest first."""
        results = []
        for filepath in self._dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text())
                results.append(data)
            except json.JSONDecodeError, OSError:
                continue

        results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return results

    def delete(self, backtest_id: str) -> bool:
        """Delete results for a specific backtest run."""
        filepath = self._dir / f"{backtest_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False
