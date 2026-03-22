"""Backtest CLI — launch, monitor, and compare backtest runs.

Usage:
    python -m backtest_svc.cli run --symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00
    python -m backtest_svc.cli run --symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00 --speed real_time
    python -m backtest_svc.cli run --symbol BTCUSD --start 2026-03-21T00:00:00 --end 2026-03-21T12:00:00 --speed scaled --multiplier 10
    python -m backtest_svc.cli list
    python -m backtest_svc.cli results --backtest-id bt-abc123
"""

from __future__ import annotations

import argparse
import json
import logging

from backtest_svc.replay import BacktestConfig, ReplayEngine, ReplaySpeed
from backtest_svc.results import BacktestResultStore
from quant_core.config import AppConfig
from quant_core.kafka_utils import QProducer
from quant_core.logging import setup_logging

logger = logging.getLogger(__name__)


def run_backtest(args: argparse.Namespace) -> None:
    """Execute a backtest replay."""
    config = AppConfig.from_env()
    setup_logging("backtest-cli", level="INFO")

    bt_config = BacktestConfig(
        backtest_id=args.backtest_id or "",
        symbol=args.symbol.upper(),
        start_time=args.start,
        end_time=args.end,
        replay_speed=ReplaySpeed(args.speed),
        speed_multiplier=args.multiplier,
        include_depth=not args.no_depth,
    )

    logger.info("Backtest ID: %s", bt_config.backtest_id)

    # Create producer with backtest_id injection
    producer = QProducer(config.kafka, backtest_id=bt_config.backtest_id)

    engine = ReplayEngine(
        db_url=config.database.url,
        kafka_producer=producer,
        config=bt_config,
    )

    stats = engine.run()

    # Store results
    store = BacktestResultStore()
    store.save(stats, bt_config)

    # Print summary
    print("\n" + "=" * 60)
    print(f"  Backtest Complete: {stats.backtest_id}")
    print("=" * 60)
    print(f"  Trades replayed:      {stats.trades_replayed:,}")
    print(f"  Depth updates:        {stats.depth_updates_replayed:,}")
    print(f"  Data span:            {stats.data_span_seconds:.1f}s")
    print(f"  Wall-clock time:      {stats.duration_seconds:.1f}s")
    print(f"  Throughput:           {stats.messages_per_second:,.0f} msg/s")
    print("=" * 60)
    print("\n  View results at: http://localhost:8080/api/pnl")
    print(f"  (set BACKTEST_ID={stats.backtest_id} on services to analyze)\n")


def list_backtests(args: argparse.Namespace) -> None:
    """List all stored backtest runs."""
    store = BacktestResultStore()
    runs = store.list_all()

    if not runs:
        print("No backtest runs found.")
        return

    print(f"\n{'ID':<20} {'Symbol':<10} {'Trades':>10} {'Duration':>10} {'Throughput':>12} {'Date'}")
    print("-" * 80)
    for run in runs:
        print(
            f"{run['backtest_id']:<20} {run.get('symbol', 'N/A'):<10} "
            f"{run['trades_replayed']:>10,} {run['duration_seconds']:>9.1f}s "
            f"{run['messages_per_second']:>11,.0f}/s {run.get('timestamp', 'N/A')}"
        )
    print()


def show_results(args: argparse.Namespace) -> None:
    """Show detailed results for a specific backtest run."""
    store = BacktestResultStore()
    result = store.get(args.backtest_id)

    if result is None:
        print(f"No results found for backtest ID: {args.backtest_id}")
        return

    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quant System Backtest CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute a backtest replay")
    run_parser.add_argument("--symbol", required=True, help="Trading symbol (e.g., BTCUSD)")
    run_parser.add_argument("--start", required=True, help="Start time (ISO 8601 or YYYY-MM-DD HH:MM:SS)")
    run_parser.add_argument("--end", required=True, help="End time")
    run_parser.add_argument("--backtest-id", default="", help="Custom backtest ID (auto-generated if omitted)")
    run_parser.add_argument(
        "--speed",
        default="as_fast_as_possible",
        choices=["as_fast_as_possible", "real_time", "scaled"],
        help="Replay speed mode",
    )
    run_parser.add_argument("--multiplier", type=float, default=1.0, help="Speed multiplier (for scaled mode)")
    run_parser.add_argument("--no-depth", action="store_true", help="Skip depth/order book replay")

    # list command
    subparsers.add_parser("list", help="List all backtest runs")

    # results command
    results_parser = subparsers.add_parser("results", help="Show results for a backtest run")
    results_parser.add_argument("--backtest-id", required=True, help="Backtest ID to look up")

    args = parser.parse_args()

    if args.command == "run":
        run_backtest(args)
    elif args.command == "list":
        list_backtests(args)
    elif args.command == "results":
        show_results(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
