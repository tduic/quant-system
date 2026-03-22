"""Backtest-specific analysis: alpha decay and per-symbol breakdowns.

Deferred from Phase 8 (alpha decay per backtest) and Phase 9
(per-symbol backtest analysis). This module computes post-trade
analytics for a completed backtest run and stores them alongside
the replay stats.

Usage:
    After a backtest replay completes and post-trade has processed
    the fills, call `analyze_backtest_run()` with the fill/signal
    data to compute and persist:
      - Per-symbol PnL, Sharpe, drawdown, fill count
      - Alpha decay IC at each horizon, per-strategy
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Alpha decay analysis for a backtest run
# ---------------------------------------------------------------------------


@dataclass
class BacktestSignal:
    """A signal emitted during a backtest run."""

    signal_id: str = ""
    timestamp_ms: int = 0
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    strength: float = 0.0
    mid_price: float = 0.0


@dataclass
class HorizonIC:
    """IC at a single time horizon."""

    horizon_ms: int = 0
    horizon_label: str = ""
    ic: float | None = None
    filled_count: int = 0


@dataclass
class StrategyAlphaDecay:
    """Alpha decay results for a single strategy."""

    strategy_id: str = ""
    signal_count: int = 0
    horizons: list[HorizonIC] = field(default_factory=list)


@dataclass
class BacktestAlphaDecay:
    """Alpha decay analysis for an entire backtest run."""

    backtest_id: str = ""
    total_signals: int = 0
    overall_horizons: list[HorizonIC] = field(default_factory=list)
    per_strategy: list[StrategyAlphaDecay] = field(default_factory=list)


DEFAULT_HORIZONS_MS = [60_000, 300_000, 900_000, 1_800_000, 3_600_000]


def _format_horizon(ms: int) -> str:
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h"


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    d = math.sqrt(vx * vy)
    if d < 1e-15:
        return None
    return cov / d


def compute_alpha_decay(
    signals: list[BacktestSignal],
    trades: list[dict],
    horizons_ms: list[int] | None = None,
) -> BacktestAlphaDecay:
    """Compute alpha decay IC for a set of signals and trade data.

    Args:
        signals: Signals emitted during the backtest.
        trades: Trade dicts with 'timestamp_exchange', 'price', 'symbol'.
        horizons_ms: Time horizons to evaluate (default: 1m-1h).

    Returns:
        BacktestAlphaDecay with overall and per-strategy IC.
    """
    horizons = sorted(horizons_ms or DEFAULT_HORIZONS_MS)

    if not signals or not trades:
        return BacktestAlphaDecay(total_signals=len(signals))

    # Build price timeline per symbol: sorted [(ts, price), ...]
    price_timeline: dict[str, list[tuple[int, float]]] = {}
    for t in trades:
        sym = t.get("symbol", "")
        ts = int(t.get("timestamp_exchange", 0))
        price = float(t.get("price", 0))
        price_timeline.setdefault(sym, []).append((ts, price))

    for sym in price_timeline:
        price_timeline[sym].sort()

    # For each signal, find the realized return at each horizon
    signal_horizon_returns: list[dict[int, float | None]] = []
    for sig in signals:
        returns: dict[int, float | None] = {}
        timeline = price_timeline.get(sig.symbol, [])
        for h_ms in horizons:
            target_ts = sig.timestamp_ms + h_ms
            # Find the first trade at or after target_ts
            price_at_horizon = _find_price_at(timeline, target_ts)
            if price_at_horizon is not None and sig.mid_price > 0:
                returns[h_ms] = (price_at_horizon - sig.mid_price) / sig.mid_price
            else:
                returns[h_ms] = None
        signal_horizon_returns.append(returns)

    # Compute overall IC per horizon
    overall_horizons = []
    for h_ms in horizons:
        predictions = []
        actuals = []
        for i, sig in enumerate(signals):
            ret = signal_horizon_returns[i].get(h_ms)
            if ret is not None:
                direction = sig.strength if sig.side.upper() == "BUY" else -sig.strength
                predictions.append(direction)
                actuals.append(ret)

        ic = _pearson(predictions, actuals)
        overall_horizons.append(
            HorizonIC(
                horizon_ms=h_ms,
                horizon_label=_format_horizon(h_ms),
                ic=round(ic, 4) if ic is not None else None,
                filled_count=len(predictions),
            )
        )

    # Per-strategy breakdown
    strategy_indices: dict[str, list[int]] = {}
    for i, sig in enumerate(signals):
        strategy_indices.setdefault(sig.strategy_id, []).append(i)

    per_strategy = []
    for strat_id, indices in strategy_indices.items():
        strat_horizons = []
        for h_ms in horizons:
            predictions = []
            actuals = []
            for i in indices:
                ret = signal_horizon_returns[i].get(h_ms)
                if ret is not None:
                    sig = signals[i]
                    direction = sig.strength if sig.side.upper() == "BUY" else -sig.strength
                    predictions.append(direction)
                    actuals.append(ret)

            ic = _pearson(predictions, actuals)
            strat_horizons.append(
                HorizonIC(
                    horizon_ms=h_ms,
                    horizon_label=_format_horizon(h_ms),
                    ic=round(ic, 4) if ic is not None else None,
                    filled_count=len(predictions),
                )
            )

        per_strategy.append(
            StrategyAlphaDecay(
                strategy_id=strat_id,
                signal_count=len(indices),
                horizons=strat_horizons,
            )
        )

    return BacktestAlphaDecay(
        total_signals=len(signals),
        overall_horizons=overall_horizons,
        per_strategy=per_strategy,
    )


def _find_price_at(timeline: list[tuple[int, float]], target_ts: int) -> float | None:
    """Binary search for the first price at or after target_ts."""
    if not timeline:
        return None

    lo, hi = 0, len(timeline) - 1
    if target_ts > timeline[-1][0]:
        return None  # beyond data range

    while lo < hi:
        mid = (lo + hi) // 2
        if timeline[mid][0] < target_ts:
            lo = mid + 1
        else:
            hi = mid

    return timeline[lo][1]


# ---------------------------------------------------------------------------
# Per-symbol backtest analysis
# ---------------------------------------------------------------------------


@dataclass
class SymbolMetrics:
    """Performance metrics for a single symbol in a backtest."""

    symbol: str = ""
    num_fills: int = 0
    total_return: float = 0.0
    realized_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    avg_slippage_bps: float = 0.0
    total_fees: float = 0.0
    buy_fills: int = 0
    sell_fills: int = 0


@dataclass
class PerSymbolAnalysis:
    """Per-symbol breakdown for a backtest run."""

    backtest_id: str = ""
    symbols: list[SymbolMetrics] = field(default_factory=list)
    best_symbol: str = ""
    worst_symbol: str = ""


def compute_per_symbol_analysis(
    fills: list[dict],
    initial_equity_per_symbol: float = 100_000.0,
) -> PerSymbolAnalysis:
    """Compute per-symbol metrics from a list of fill dicts.

    Args:
        fills: List of fill dicts with keys: symbol, side, quantity,
               fill_price, fee, slippage_bps.
        initial_equity_per_symbol: Starting equity per symbol for return calc.

    Returns:
        PerSymbolAnalysis with per-symbol metrics.
    """
    if not fills:
        return PerSymbolAnalysis()

    # Group fills by symbol
    by_symbol: dict[str, list[dict]] = {}
    for f in fills:
        sym = f.get("symbol", "")
        by_symbol.setdefault(sym, []).append(f)

    symbol_metrics = []
    for sym, sym_fills in sorted(by_symbol.items()):
        m = _compute_symbol_metrics(sym, sym_fills, initial_equity_per_symbol)
        symbol_metrics.append(m)

    result = PerSymbolAnalysis(symbols=symbol_metrics)

    if symbol_metrics:
        best = max(symbol_metrics, key=lambda m: m.total_return)
        worst = min(symbol_metrics, key=lambda m: m.total_return)
        result.best_symbol = best.symbol
        result.worst_symbol = worst.symbol

    return result


def _compute_symbol_metrics(
    symbol: str,
    fills: list[dict],
    initial_equity: float,
) -> SymbolMetrics:
    """Compute metrics for a single symbol from its fills."""
    position = 0.0
    avg_entry = 0.0
    realized_pnl = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    wins = 0
    buy_count = 0
    sell_count = 0

    # Track equity curve for Sharpe and drawdown
    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    returns: list[float] = []
    prev_equity = initial_equity

    for f in fills:
        side = f.get("side", "BUY")
        qty = float(f.get("quantity", 0))
        price = float(f.get("fill_price", 0))
        fee = float(f.get("fee", 0))
        slippage = float(f.get("slippage_bps", 0))

        total_fees += fee
        total_slippage += slippage

        if side == "BUY":
            buy_count += 1
            signed_qty = qty
        else:
            sell_count += 1
            signed_qty = -qty

        # Compute realized PnL on position reduction
        fill_pnl = 0.0
        if position != 0 and ((position > 0 and signed_qty < 0) or (position < 0 and signed_qty > 0)):
            close_qty = min(abs(signed_qty), abs(position))
            fill_pnl = close_qty * (price - avg_entry) * (1 if position > 0 else -1)
            realized_pnl += fill_pnl - fee

            if fill_pnl > fee:
                wins += 1
        else:
            realized_pnl -= fee

        # Update position and average entry
        new_position = position + signed_qty
        if abs(new_position) > abs(position):
            # Adding to position — update avg entry
            if position == 0:
                avg_entry = price
            else:
                total_cost = avg_entry * abs(position) + price * abs(signed_qty)
                avg_entry = total_cost / (abs(position) + abs(signed_qty))
        elif new_position == 0:
            avg_entry = 0.0
        position = new_position

        # Update equity
        equity = initial_equity + realized_pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)

        if prev_equity > 0:
            returns.append((equity - prev_equity) / prev_equity)
        prev_equity = equity

    # Sharpe
    sharpe = 0.0
    if len(returns) >= 2:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = var_r**0.5
        if std_r > 0:
            sharpe = (mean_r / std_r) * math.sqrt(365)

    total_return = (equity - initial_equity) / initial_equity if initial_equity > 0 else 0.0
    win_rate = wins / len(fills) if fills else 0.0
    avg_slip = total_slippage / len(fills) if fills else 0.0

    return SymbolMetrics(
        symbol=symbol,
        num_fills=len(fills),
        total_return=round(total_return, 6),
        realized_pnl=round(realized_pnl, 2),
        max_drawdown=round(max_dd, 6),
        sharpe=round(sharpe, 4),
        win_rate=round(win_rate, 4),
        avg_slippage_bps=round(avg_slip, 2),
        total_fees=round(total_fees, 4),
        buy_fills=buy_count,
        sell_fills=sell_count,
    )


# ---------------------------------------------------------------------------
# Combined analysis + result store integration
# ---------------------------------------------------------------------------


def analyze_backtest_run(
    backtest_id: str,
    signals: list[BacktestSignal] | None = None,
    trades: list[dict] | None = None,
    fills: list[dict] | None = None,
    horizons_ms: list[int] | None = None,
) -> dict:
    """Run full backtest analysis and return results dict.

    Combines alpha decay and per-symbol analysis into a single dict
    that can be merged into the backtest result store.
    """
    result: dict = {"backtest_id": backtest_id}

    # Alpha decay
    if signals and trades:
        decay = compute_alpha_decay(signals, trades, horizons_ms)
        result["alpha_decay"] = {
            "total_signals": decay.total_signals,
            "overall_horizons": [
                {
                    "horizon_ms": h.horizon_ms,
                    "horizon_label": h.horizon_label,
                    "ic": h.ic,
                    "filled_count": h.filled_count,
                }
                for h in decay.overall_horizons
            ],
            "per_strategy": [
                {
                    "strategy_id": s.strategy_id,
                    "signal_count": s.signal_count,
                    "horizons": [
                        {
                            "horizon_ms": h.horizon_ms,
                            "horizon_label": h.horizon_label,
                            "ic": h.ic,
                            "filled_count": h.filled_count,
                        }
                        for h in s.horizons
                    ],
                }
                for s in decay.per_strategy
            ],
        }

    # Per-symbol analysis
    if fills:
        sym_analysis = compute_per_symbol_analysis(fills)
        result["per_symbol"] = {
            "best_symbol": sym_analysis.best_symbol,
            "worst_symbol": sym_analysis.worst_symbol,
            "symbols": [
                {
                    "symbol": m.symbol,
                    "num_fills": m.num_fills,
                    "total_return": m.total_return,
                    "realized_pnl": m.realized_pnl,
                    "max_drawdown": m.max_drawdown,
                    "sharpe": m.sharpe,
                    "win_rate": m.win_rate,
                    "avg_slippage_bps": m.avg_slippage_bps,
                    "total_fees": m.total_fees,
                    "buy_fills": m.buy_fills,
                    "sell_fills": m.sell_fills,
                }
                for m in sym_analysis.symbols
            ],
        }

    return result
