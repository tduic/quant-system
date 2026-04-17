"""Async analysis job runner with in-memory job store.

Submits analysis tasks to a background thread pool and tracks their
status so the dashboard can poll for results.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):  # noqa: UP042 — StrEnum needs 3.11+
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AnalysisJob:
    job_id: str
    analysis_type: str
    params: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = 0.0
    completed_at: float | None = None


class JobStore:
    """Thread-safe in-memory store for analysis jobs."""

    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, AnalysisJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analysis")

    def submit(self, analysis_type: str, params: dict[str, Any]) -> str:
        import time

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = AnalysisJob(
            job_id=job_id,
            analysis_type=analysis_type,
            params=params,
            status=JobStatus.PENDING,
            created_at=time.time(),
        )
        with self._lock:
            self._jobs[job_id] = job

        self._executor.submit(self._run_job, job_id)
        return job_id

    def get(self, job_id: str) -> AnalysisJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[AnalysisJob]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def _update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)

    def _run_job(self, job_id: str) -> None:
        import time

        self._update(job_id, status=JobStatus.RUNNING, progress=10)

        job = self.get(job_id)
        if not job:
            return

        try:
            result = _execute_analysis(job.analysis_type, job.params, self, job_id)
            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                result=result,
                progress=100,
                completed_at=time.time(),
            )
            logger.info("Job %s completed: %s", job_id, job.analysis_type)
        except Exception:
            tb = traceback.format_exc()
            logger.exception("Job %s failed", job_id)
            self._update(
                job_id,
                status=JobStatus.FAILED,
                error=tb,
                completed_at=time.time(),
            )


# ---------------------------------------------------------------------------
# Analysis execution — runs in thread pool
# ---------------------------------------------------------------------------

# Import backtest modules lazily to avoid circular imports and keep
# the post-trade service startable without the backtest package installed.


def _load_historical_trades(backtest_id: str) -> list[dict]:
    """Load trades from a historical backtest run's trade file.

    Searches .backtest_results/ for JSONL trade data associated with the
    given backtest_id.
    """
    import json
    import os

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", ".backtest_results"),
        os.path.join(os.path.dirname(__file__), "..", ".backtest_results"),
        ".backtest_results",
    ]
    for base in candidates:
        base = os.path.abspath(base)
        # Try trades file (JSONL)
        trades_path = os.path.join(base, f"{backtest_id}_trades.jsonl")
        if os.path.isfile(trades_path):
            trades = []
            with open(trades_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        trades.append(json.loads(line))
            if trades:
                logger.info("Loaded %d historical trades from %s", len(trades), trades_path)
                return trades

        # Try JSON array format
        trades_json = os.path.join(base, f"{backtest_id}_trades.json")
        if os.path.isfile(trades_json):
            with open(trades_json) as f:
                data = json.load(f)
            trades = data if isinstance(data, list) else data.get("trades", [])
            if trades:
                logger.info("Loaded %d historical trades from %s", len(trades), trades_json)
                return trades

    msg = f"No trade data found for backtest {backtest_id}"
    raise FileNotFoundError(msg)


def _list_historical_backtests() -> list[dict[str, Any]]:
    """List available backtest runs that have trade data files."""
    import json
    import os

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", ".backtest_results"),
        os.path.join(os.path.dirname(__file__), "..", ".backtest_results"),
        ".backtest_results",
    ]
    results = []
    seen_ids: set[str] = set()

    for base in candidates:
        base = os.path.abspath(base)
        if not os.path.isdir(base):
            continue
        for fname in os.listdir(base):
            if not fname.endswith(".json"):
                continue
            # Skip trade data files — we want the metadata files
            if "_trades." in fname:
                continue
            fpath = os.path.join(base, fname)
            try:
                with open(fpath) as f:
                    data = json.load(f)
                bid = data.get("backtest_id", fname.replace(".json", ""))
                if bid in seen_ids:
                    continue
                seen_ids.add(bid)
                # Check if trade data exists for this run
                has_trades = any(
                    os.path.isfile(os.path.join(base, f"{bid}{ext}")) for ext in ("_trades.jsonl", "_trades.json")
                )
                results.append(
                    {
                        "backtest_id": bid,
                        "symbol": data.get("symbol", "unknown"),
                        "timestamp": data.get("timestamp", ""),
                        "trades_replayed": data.get("trades_replayed", 0),
                        "duration_seconds": data.get("duration_seconds", 0),
                        "has_trades": has_trades,
                    }
                )
            except json.JSONDecodeError, OSError:
                continue

    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return results


def _make_trades(params: dict[str, Any], *, strategy: str = "mean_reversion") -> list[dict]:
    """Generate synthetic trade data for analysis.

    For pairs trading, generates interleaved trades for two correlated symbols.
    """
    import random

    symbol_a = params.get("symbol", "BTCUSD")
    symbol_b = params.get("symbol_b", "ETHUSD")
    n = int(params.get("num_trades", 1000))
    seed = params.get("seed", 42)

    rng = random.Random(seed)

    # Spread trades across a realistic multi-day window so Sharpe (hourly
    # bucketed) has enough buckets to be meaningful. 7 days default.
    span_ms = int(params.get("span_ms", 7 * 24 * 60 * 60 * 1000))
    start_ts = 1_700_000_000_000  # arbitrary Unix ms
    dt_ms = max(1, span_ms // max(n, 1))

    if strategy == "pairs_trading":
        # Generate two correlated price series
        price_a = 50000.0
        price_b = 3500.0
        trades = []
        for i in range(n):
            shared = rng.gauss(0, 30)
            price_a += shared + rng.gauss(0, 20) - (price_a - 50000) * 0.001
            price_b += shared * 0.07 + rng.gauss(0, 1.5) - (price_b - 3500) * 0.001
            price_a = max(price_a, 100)
            price_b = max(price_b, 10)
            ts = start_ts + i * dt_ms
            trades.append(
                {
                    "symbol": symbol_a,
                    "price": round(price_a, 2),
                    "quantity": round(rng.uniform(0.001, 0.1), 4),
                    "timestamp_exchange": ts,
                    "is_buyer_maker": rng.random() > 0.5,
                }
            )
            trades.append(
                {
                    "symbol": symbol_b,
                    "price": round(price_b, 2),
                    "quantity": round(rng.uniform(0.01, 1.0), 4),
                    "timestamp_exchange": ts + dt_ms // 2,
                    "is_buyer_maker": rng.random() > 0.5,
                }
            )
        return trades

    # Single-symbol strategies (mean_reversion, etc.)
    price = 50000.0
    trades = []
    for i in range(n):
        price += rng.gauss(0, 50) - (price - 50000) * 0.001
        price = max(price, 100)
        trades.append(
            {
                "symbol": symbol_a,
                "price": round(price, 2),
                "quantity": round(rng.uniform(0.001, 0.1), 4),
                "timestamp_exchange": start_ts + i * dt_ms,
                "is_buyer_maker": rng.random() > 0.5,
            }
        )
    return trades


def _execute_analysis(
    analysis_type: str,
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    """Dispatch to the correct analysis module."""
    # These imports are from the backtest service — they live in a sibling
    # package. We add the backtest service to sys.path at import time.
    # In Docker the backtest code is at /app/backtest; locally it's at
    # ../../backtest relative to this file.
    import os
    import sys

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "backtest"),  # local
        os.path.join(os.path.dirname(__file__), "..", "backtest"),  # Docker /app
    ]
    for p in candidates:
        p = os.path.abspath(p)
        if p not in sys.path and os.path.isdir(os.path.join(p, "backtest_svc")):
            sys.path.insert(0, p)
            break

    from backtest_svc.evaluator import EvaluatorConfig, LocalStrategyEvaluator

    strategy = params.get("strategy", "mean_reversion")
    symbol = params.get("symbol", "BTCUSD")

    # Data source: "historical" loads from a previous backtest run,
    # "generated" (default) creates synthetic data.
    data_source = params.get("data_source", "generated")
    if data_source == "historical":
        backtest_id = params.get("backtest_id")
        if not backtest_id:
            msg = "backtest_id is required when data_source is 'historical'"
            raise ValueError(msg)
        trades = _load_historical_trades(backtest_id)
        logger.info("Using %d historical trades from backtest %s", len(trades), backtest_id)
    else:
        trades = _make_trades(params, strategy=strategy)

    config = EvaluatorConfig(
        strategy_type=strategy,
        symbol=symbol,
        fee_rate=float(params.get("fee_rate", 0.006)),
        slippage_bps=float(params.get("slippage_bps", 1.0)),
    )
    evaluator = LocalStrategyEvaluator(config)

    if analysis_type == "sensitivity":
        return _run_sensitivity(evaluator, trades, params, store, job_id)
    if analysis_type == "walk_forward":
        return _run_walk_forward(evaluator, trades, params, store, job_id)
    if analysis_type == "monte_carlo":
        return _run_monte_carlo(evaluator, trades, params, store, job_id)
    if analysis_type == "cost_sweep":
        return _run_cost_sweep(evaluator, trades, params, store, job_id)
    if analysis_type == "validate":
        return _run_validate(evaluator, trades, params, store, job_id)
    if analysis_type == "run_all":
        return _run_all(evaluator, trades, params, store, job_id)

    msg = f"Unknown analysis type: {analysis_type}"
    raise ValueError(msg)


def _run_sensitivity(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    from backtest_svc.param_sensitivity import ParamRange, SearchMethod, run_sensitivity

    strategy = params.get("strategy", "mean_reversion")
    if strategy == "mean_reversion":
        param_ranges = [
            ParamRange(name="threshold_std", values=[1.0, 1.5, 2.0, 2.5, 3.0]),
            ParamRange(name="window_size", values=[50, 100, 200]),
            ParamRange(name="cooldown_trades", values=[5, 10, 20]),
        ]
    else:
        param_ranges = [
            ParamRange(name="entry_threshold", values=[1.5, 2.0, 2.5, 3.0]),
            ParamRange(name="min_correlation", values=[0.3, 0.5, 0.7]),
            ParamRange(name="window", values=[50, 100, 200]),
        ]

    store._update(job_id, progress=30)

    method = SearchMethod.RANDOM if params.get("random_search") else SearchMethod.GRID
    result = run_sensitivity(
        trades,
        evaluator,
        param_ranges,
        method=method,
        n_random_samples=int(params.get("random_samples", 50)),
        random_seed=params.get("seed"),
    )

    store._update(job_id, progress=90)

    return {
        "best_params": result.best_params,
        "best_sharpe": result.best_sharpe,
        "num_evaluations": result.num_evaluations,
        "search_method": result.search_method,
        "param_impacts": [
            {
                "name": i.param_name,
                "sharpe_range": round(i.sharpe_range, 4),
                "correlation": round(i.correlation_with_sharpe, 3),
                "best_value": i.best_value,
                "worst_value": i.worst_value,
            }
            for i in result.param_impacts
        ],
    }


def _run_walk_forward(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    from backtest_svc.param_sensitivity import ParamRange, build_grid
    from backtest_svc.walk_forward import WalkForwardConfig, WindowType, run_walk_forward

    strategy = params.get("strategy", "mean_reversion")
    if strategy == "mean_reversion":
        param_ranges = [
            ParamRange(name="threshold_std", values=[1.5, 2.0, 2.5]),
            ParamRange(name="window_size", values=[50, 100]),
        ]
    else:
        param_ranges = [
            ParamRange(name="entry_threshold", values=[1.5, 2.0, 2.5]),
            ParamRange(name="min_correlation", values=[0.3, 0.5]),
        ]

    store._update(job_id, progress=20)

    param_grid = build_grid(param_ranges)
    window_type = WindowType.EXPANDING if params.get("expanding") else WindowType.ROLLING

    wf_config = WalkForwardConfig(
        n_splits=int(params.get("splits", 5)),
        train_pct=float(params.get("train_pct", 0.7)),
        window_type=window_type,
        min_train_size=int(params.get("min_train", 50)),
        min_test_size=int(params.get("min_test", 20)),
    )

    store._update(job_id, progress=40)
    result = run_walk_forward(trades, evaluator, param_grid, wf_config)
    store._update(job_id, progress=90)

    return {
        "mean_test_sharpe": round(result.mean_test_sharpe, 4),
        "std_test_sharpe": round(result.std_test_sharpe, 4),
        "mean_test_return": round(result.mean_test_return, 6),
        "overfitting_ratio": round(result.overfitting_ratio, 2),
        "degradation_pct": round(result.degradation_pct, 1),
        "folds": [
            {
                "fold": f.fold_index,
                "train_sharpe": round(f.train_sharpe, 4),
                "test_sharpe": round(f.test_sharpe, 4),
                "best_params": f.best_params,
            }
            for f in result.folds
        ],
    }


def _run_monte_carlo(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    from backtest_svc.monte_carlo import MonteCarloConfig, run_monte_carlo

    store._update(job_id, progress=20)

    # Build equity from a baseline run
    baseline = evaluator.evaluate(trades, {})
    initial = 100_000.0
    final = initial * (1 + baseline["total_return"])
    n_eq = max(len(trades) // 10, 2)
    step = (final - initial) / n_eq
    equity = [initial + i * step for i in range(n_eq + 1)]

    store._update(job_id, progress=40)

    mc_config = MonteCarloConfig(
        n_simulations=int(params.get("simulations", 1000)),
        block_size=int(params.get("block_size", 1)),
        seed=params.get("seed"),
    )
    result = run_monte_carlo(equity, mc_config)

    store._update(job_id, progress=90)

    return {
        "observed_sharpe": round(result.observed_sharpe, 4),
        "observed_return": round(result.observed_total_return, 6),
        "observed_max_drawdown": round(result.observed_max_drawdown, 6),
        "prob_positive_sharpe": round(result.prob_positive_sharpe, 4),
        "prob_sharpe_above_1": round(result.prob_sharpe_above_1, 4),
        "sharpe_mean": round(result.sharpe_distribution.mean, 4),
        "sharpe_std": round(result.sharpe_distribution.std, 4),
        "confidence_intervals": [
            {"level": round(ci.level, 2), "value": round(ci.value, 4)}
            for ci in result.sharpe_distribution.confidence_intervals
        ],
    }


def _run_cost_sweep(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    from backtest_svc.sensitivity_sweep import SweepConfig, run_sensitivity_sweep

    store._update(job_id, progress=20)

    sweep_config = SweepConfig(
        fee_rates=[0.001, 0.002, 0.004, 0.006, 0.008, 0.01],
        slippage_bps=[0.0, 1.0, 2.5, 5.0, 10.0, 20.0],
        sweep_dimensions=params.get("dimensions", ["fee_rate", "slippage_bps"]),
    )

    result = run_sensitivity_sweep(
        trades,
        evaluator,
        base_params={"threshold_std": 2.0},
        config=sweep_config,
    )

    store._update(job_id, progress=90)

    return {
        "num_scenarios": len(result.points),
        "best_sharpe": round(result.best_case.sharpe, 4),
        "best_fee_rate": round(result.best_case.fee_rate, 4),
        "best_slippage_bps": round(result.best_case.slippage_bps, 1),
        "worst_sharpe": round(result.worst_case.sharpe, 4),
        "worst_fee_rate": round(result.worst_case.fee_rate, 4),
        "worst_slippage_bps": round(result.worst_case.slippage_bps, 1),
        "breakeven_fee": round(result.breakeven.max_fee_rate, 4),
        "breakeven_slippage_bps": round(result.breakeven.max_slippage_bps, 1),
        "sensitivity_to_fees": round(result.sharpe_sensitivity_to_fees, 2),
        "sensitivity_to_slippage": round(result.sharpe_sensitivity_to_slippage, 4),
    }


def _run_validate(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    from backtest_svc.monte_carlo import MonteCarloConfig, run_monte_carlo
    from backtest_svc.param_sensitivity import ParamRange, build_grid
    from backtest_svc.sensitivity_sweep import SweepConfig, run_sensitivity_sweep
    from backtest_svc.validation import generate_validation_report
    from backtest_svc.walk_forward import WalkForwardConfig, run_walk_forward

    store._update(job_id, progress=10)

    # Walk-forward
    param_grid = build_grid(
        [
            ParamRange(name="threshold_std", values=[1.5, 2.0, 2.5]),
            ParamRange(name="window_size", values=[50, 100]),
        ]
    )
    wf_result = run_walk_forward(
        trades,
        evaluator,
        param_grid,
        WalkForwardConfig(
            n_splits=int(params.get("splits", 5)),
            min_train_size=50,
            min_test_size=20,
        ),
    )
    store._update(job_id, progress=35)

    # Monte Carlo
    baseline = evaluator.evaluate(trades, {"threshold_std": 2.0})
    initial = 100_000.0
    final = initial * (1 + baseline["total_return"])
    n_eq = max(len(trades) // 10, 2)
    step = (final - initial) / n_eq
    equity = [initial + i * step for i in range(n_eq + 1)]
    mc_result = run_monte_carlo(
        equity,
        MonteCarloConfig(
            n_simulations=int(params.get("simulations", 500)),
            seed=params.get("seed"),
        ),
    )
    store._update(job_id, progress=65)

    # Cost sweep
    sweep_result = run_sensitivity_sweep(
        trades,
        evaluator,
        base_params={"threshold_std": 2.0},
        config=SweepConfig(sweep_dimensions=["fee_rate", "slippage_bps"]),
    )
    store._update(job_id, progress=85)

    report = generate_validation_report(wf_result, mc_result, sweep_result)

    return {
        "grade": report.grade.value,
        "mean_oos_sharpe": round(report.mean_oos_sharpe, 4),
        "overfitting_ratio": round(report.overfitting_ratio, 2),
        "prob_positive_sharpe": round(report.prob_positive_sharpe, 4),
        "max_profitable_fee": round(report.max_profitable_fee, 4),
        "max_profitable_slippage_bps": round(report.max_profitable_slippage_bps, 1),
        "summary": report.summary,
        "flags": [
            {
                "category": f.category,
                "severity": f.severity,
                "message": f.message,
            }
            for f in report.flags
        ],
    }


def _run_all(
    evaluator: Any,
    trades: list[dict],
    params: dict[str, Any],
    store: JobStore,
    job_id: str,
) -> dict[str, Any]:
    """Run all five analysis types and return combined results."""
    store._update(job_id, progress=5)

    sensitivity = _run_sensitivity(evaluator, trades, params, store, job_id)
    store._update(job_id, progress=20)

    walk_forward = _run_walk_forward(evaluator, trades, params, store, job_id)
    store._update(job_id, progress=40)

    monte_carlo = _run_monte_carlo(evaluator, trades, params, store, job_id)
    store._update(job_id, progress=60)

    cost_sweep = _run_cost_sweep(evaluator, trades, params, store, job_id)
    store._update(job_id, progress=80)

    validate = _run_validate(evaluator, trades, params, store, job_id)
    store._update(job_id, progress=95)

    return {
        "sensitivity": sensitivity,
        "walk_forward": walk_forward,
        "monte_carlo": monte_carlo,
        "cost_sweep": cost_sweep,
        "validate": validate,
    }
