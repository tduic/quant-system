"""Strategy evaluator — runs the live strategy code over historical trades.

This is the adapter that connects the abstract StrategyEvaluator protocol
(used by walk-forward, param sensitivity, etc.) to the actual Alpha Engine
strategies (MeanReversion, PairsTradingStrategy) and Execution service
fill simulator — so backtests and live trading share the same code path.

This module has NO external service dependencies (no Kafka, no DB, no Redis) —
it operates entirely on in-memory trade lists, making it suitable for
fast parameter sweeps.
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Ensure alpha-engine and execution services are importable (for CLI use,
# not just tests). conftest.py handles this for pytest.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
for _svc in ("alpha-engine", "execution"):
    _path = str(_PROJECT_ROOT / "services" / _svc)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from alpha_engine_svc.cross_asset import CrossAssetTracker  # noqa: E402
from alpha_engine_svc.strategies.mean_reversion import MeanReversionStrategy  # noqa: E402
from alpha_engine_svc.strategies.pairs_trading import PairsTradingStrategy  # noqa: E402
from execution_svc.fill_simulator import FillSimulator  # noqa: E402
from quant_core.models import DepthUpdate, Fill, Order, Signal, Trade  # noqa: E402


@dataclass
class EvaluatorConfig:
    """Configuration for the evaluator."""

    fee_rate: float | None = None  # None → use Coinbase tiered fees (realistic default)
    slippage_bps: float = 1.0  # additional slippage in basis points (rarely used now)
    initial_equity: float = 100_000.0
    strategy_type: str = "mean_reversion"  # or "pairs_trading"
    symbol: str = "BTCUSD"
    symbol_b: str = "ETHUSD"  # for pairs trading


# ---------------------------------------------------------------------------
# Metrics computation from fills
# ---------------------------------------------------------------------------

# Sharpe is computed on time-bucketed equity returns. Bucket size auto-scales
# to the data span so short backtests still produce a meaningful Sharpe.
# Per-fill returns with a fixed annualization factor is mathematically invalid —
# it inflates volatility proportional to trade frequency.
MS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0 * 1000.0
HOUR_MS = 60 * 60 * 1000
MINUTE_MS = 60 * 1000


def _pick_bucket_ms(span_ms: int) -> int:
    """Pick a bucketing interval that yields at least ~24 buckets across span."""
    if span_ms >= 48 * HOUR_MS:
        return HOUR_MS  # 48h+ of data → hourly
    if span_ms >= 2 * HOUR_MS:
        return 5 * MINUTE_MS  # 2h–48h → 5-minute buckets
    return MINUTE_MS  # shorter windows → per-minute


def _compute_metrics_from_fills(
    fills: list[Fill],
    initial_equity: float,
    signals_emitted: int = 0,
) -> dict[str, float]:
    """Compute Sharpe, return, drawdown, etc. from a list of fills.

    Sharpe uses hourly equity returns with proper annualization.
    """
    if not fills:
        return {
            "sharpe": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "num_trades": 0,
            "num_signals": signals_emitted,
            "total_costs": 0.0,
        }

    # Track position and PnL
    position = 0.0
    avg_entry = 0.0
    realized_pnl = 0.0
    total_fees = 0.0
    total_slippage_cost = 0.0

    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0

    # Pick bucket size based on data span
    ts_min = min(f.timestamp for f in fills if f.timestamp > 0) if fills else 0
    ts_max = max(f.timestamp for f in fills if f.timestamp > 0) if fills else 0
    span_ms = max(1, ts_max - ts_min)
    bucket_ms = _pick_bucket_ms(span_ms)

    # Bucketed equity snapshots for Sharpe calculation
    bucket_equity: dict[int, float] = {}

    for f in fills:
        total_fees += f.fee
        slip_cost = f.quantity * f.fill_price * f.slippage_bps / 10_000.0
        total_slippage_cost += slip_cost

        signed_qty = f.quantity if f.side == "BUY" else -f.quantity

        # PnL on position reduction
        if position != 0 and ((position > 0 and signed_qty < 0) or (position < 0 and signed_qty > 0)):
            close_qty = min(abs(signed_qty), abs(position))
            fill_pnl = close_qty * (f.fill_price - avg_entry) * (1 if position > 0 else -1)
            realized_pnl += fill_pnl - f.fee - slip_cost
        else:
            realized_pnl -= f.fee + slip_cost

        # Update position
        new_position = position + signed_qty
        if abs(new_position) > abs(position):
            if position == 0:
                avg_entry = f.fill_price
            else:
                total_cost = avg_entry * abs(position) + f.fill_price * abs(signed_qty)
                avg_entry = total_cost / (abs(position) + abs(signed_qty))
        elif new_position == 0:
            avg_entry = 0.0
        position = new_position

        # Update equity and drawdown
        equity = initial_equity + realized_pnl
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)

        # Record latest equity in the fill's time bucket
        bucket = f.timestamp // bucket_ms if f.timestamp > 0 else 0
        bucket_equity[bucket] = equity

    # Bucketed returns for Sharpe
    sharpe = 0.0
    if len(bucket_equity) >= 2:
        buckets = sorted(bucket_equity.keys())
        bucket_returns: list[float] = []
        prev = initial_equity
        for b in buckets:
            e = bucket_equity[b]
            if prev > 0:
                bucket_returns.append((e - prev) / prev)
            prev = e

        if len(bucket_returns) >= 2:
            mean_r = sum(bucket_returns) / len(bucket_returns)
            var_r = sum((r - mean_r) ** 2 for r in bucket_returns) / (len(bucket_returns) - 1)
            std_r = var_r**0.5
            if std_r > 0:
                # Annualize: buckets_per_year = MS_PER_YEAR / bucket_ms
                sharpe = (mean_r / std_r) * math.sqrt(MS_PER_YEAR / bucket_ms)

    total_return = (equity - initial_equity) / initial_equity if initial_equity > 0 else 0.0

    return {
        "sharpe": sharpe,
        "total_return": total_return,
        "max_drawdown": max_dd,
        "num_trades": len(fills),
        "num_signals": signals_emitted,
        "total_costs": total_fees + total_slippage_cost,
        "total_fees": total_fees,
        "total_slippage_cost": total_slippage_cost,
        "realized_pnl": realized_pnl,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dict_to_trade(t: dict, default_symbol: str) -> Trade:
    """Convert a trade dict (as loaded from storage) into a Trade model."""
    return Trade(
        symbol=t.get("symbol", default_symbol),
        price=float(t.get("price", 0.0)),
        quantity=float(t.get("quantity", 0.0)),
        is_buyer_maker=bool(t.get("is_buyer_maker", False)),
        timestamp_exchange=int(t.get("timestamp_exchange", 0)),
        timestamp_ingested=int(t.get("timestamp_ingested", 0)),
    )


def _signal_to_order(signal: Signal) -> Order:
    """Mirror the risk gateway's signal→order logic for backtest consistency."""
    if signal.urgency >= 0.8:
        order_type = "MARKET"
        limit_price = None
    else:
        order_type = "LIMIT"
        limit_price = signal.mid_price_at_signal
    return Order(
        timestamp=signal.timestamp,
        symbol=signal.symbol,
        side=signal.side,
        order_type=order_type,
        quantity=signal.target_quantity,
        limit_price=limit_price,
        signal_id=signal.signal_id,
        strategy_id=signal.strategy_id,
    )


# ---------------------------------------------------------------------------
# Strategy evaluator
# ---------------------------------------------------------------------------


class LocalStrategyEvaluator:
    """Evaluates a strategy by replaying trades through the live strategy code.

    Uses the same MeanReversionStrategy/PairsTradingStrategy and FillSimulator
    that the alpha engine and execution service run in production. Guarantees
    backtest and live can never diverge.

    Usage:
        evaluator = LocalStrategyEvaluator(config=EvaluatorConfig(
            strategy_type="mean_reversion",
            symbol="BTCUSD",
        ))
        metrics = evaluator.evaluate(trades, {"threshold_std": 2.5})
    """

    def __init__(self, config: EvaluatorConfig | None = None):
        self._config = config or EvaluatorConfig()

    def evaluate(
        self,
        trades: list[dict],
        params: dict[str, Any],
    ) -> dict[str, float]:
        """Run strategy on trades with given params and return metrics.

        The params dict can contain both strategy params (threshold_std,
        window_size, etc.) and cost params (fee_rate, slippage_bps).
        """
        fee_rate = params.get("fee_rate", self._config.fee_rate)
        slippage_bps = params.get("slippage_bps", self._config.slippage_bps)

        # Build strategy params (exclude cost keys)
        cost_keys = {"fee_rate", "slippage_bps", "latency_ms"}
        strategy_params = {k: v for k, v in params.items() if k not in cost_keys}

        signals, fills = self._run_strategy(
            trades=trades,
            strategy_params=strategy_params,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
        )

        return _compute_metrics_from_fills(
            fills,
            initial_equity=self._config.initial_equity,
            signals_emitted=len(signals),
        )

    def _run_strategy(
        self,
        trades: list[dict],
        strategy_params: dict[str, Any],
        fee_rate: float | None,
        slippage_bps: float,
    ) -> tuple[list[Signal], list[Fill]]:
        """Replay trades through the strategy and collect signals/fills."""
        strategy_type = self._config.strategy_type

        if strategy_type == "mean_reversion":
            return self._run_mean_reversion(trades, strategy_params, fee_rate, slippage_bps)
        if strategy_type == "pairs_trading":
            return self._run_pairs_trading(trades, strategy_params, fee_rate, slippage_bps)
        return [], []

    def _run_mean_reversion(
        self,
        trades: list[dict],
        params: dict[str, Any],
        fee_rate: float | None,
        slippage_bps: float,
    ) -> tuple[list[Signal], list[Fill]]:
        """Run the live MeanReversionStrategy over historical trades."""
        strategy = MeanReversionStrategy(
            strategy_id=f"mean_reversion_{self._config.symbol.lower()}",
            symbol=self._config.symbol,
            params=params,
        )
        simulator = FillSimulator(fee_rate=fee_rate)

        signals: list[Signal] = []
        fills: list[Fill] = []

        for t in trades:
            price = float(t.get("price", 0.0))
            if price <= 0:
                continue

            # Feed a synthetic book update so the strategy has mid/spread.
            # Use 1 bps spread as a reasonable default for backtest.
            half_spread = price * 0.00005  # 0.5 bps each side
            strategy.on_book_update(
                DepthUpdate(
                    symbol=self._config.symbol,
                    bids=[[price - half_spread, 1.0]],
                    asks=[[price + half_spread, 1.0]],
                )
            )

            trade = _dict_to_trade(t, self._config.symbol)
            signal = strategy.on_trade(trade)
            if signal is None:
                continue

            # Backfill the signal timestamp with the trade's historical time
            # (strategy uses now_ms, but backtest needs the trade's actual time).
            signal.timestamp = trade.timestamp_exchange
            signals.append(signal)
            order = _signal_to_order(signal)

            # Simulate fill at the signal's mid/spread
            fill = simulator.simulate_fill(
                order=order,
                mid_price=signal.mid_price_at_signal,
                spread=signal.spread_at_signal,
            )
            fill.timestamp = trade.timestamp_exchange
            # Apply extra configured slippage (on top of spread crossing)
            if slippage_bps > 0:
                extra_slip = fill.fill_price * slippage_bps / 10_000.0
                if order.side == "BUY":
                    fill.fill_price += extra_slip
                else:
                    fill.fill_price -= extra_slip
                fill.slippage_bps += slippage_bps

            fills.append(fill)

        return signals, fills

    def _run_pairs_trading(
        self,
        trades: list[dict],
        params: dict[str, Any],
        fee_rate: float | None,
        slippage_bps: float,
    ) -> tuple[list[Signal], list[Fill]]:
        """Run the live PairsTradingStrategy over historical trades."""
        symbol_a = self._config.symbol
        symbol_b = self._config.symbol_b

        tracker = CrossAssetTracker(window=int(params.get("window", 200)))
        strategy = PairsTradingStrategy(
            strategy_id=f"pairs_{symbol_a.lower()}_{symbol_b.lower()}",
            symbol=symbol_a,
            symbol_b=symbol_b,
            cross_asset_tracker=tracker,
            params=params,
        )
        simulator = FillSimulator(fee_rate=fee_rate)

        signals: list[Signal] = []
        fills: list[Fill] = []
        latest_price: dict[str, float] = {}

        for t in trades:
            sym = t.get("symbol", "")
            price = float(t.get("price", 0.0))
            if price <= 0 or sym not in (symbol_a, symbol_b):
                continue
            latest_price[sym] = price

            # Feed book for mid/spread
            half_spread = price * 0.00005
            if sym == symbol_a:
                strategy.on_book_update(
                    DepthUpdate(
                        symbol=sym,
                        bids=[[price - half_spread, 1.0]],
                        asks=[[price + half_spread, 1.0]],
                    )
                )
                trade = _dict_to_trade(t, sym)
                signal = strategy.on_trade(trade)
            else:
                # Symbol B trade still feeds the tracker
                tracker.on_price(sym, int(t.get("timestamp_exchange", 0)), price)
                signal = None

            if signal is not None:
                trade_ts = int(t.get("timestamp_exchange", 0))
                signal.timestamp = trade_ts
                signals.append(signal)
                order = _signal_to_order(signal)
                fill = simulator.simulate_fill(
                    order=order,
                    mid_price=signal.mid_price_at_signal,
                    spread=signal.spread_at_signal,
                )
                fill.timestamp = trade_ts
                fills.append(fill)

                # Counterpart leg on symbol_b
                counterpart = strategy.get_counterpart_signal()
                if counterpart is not None and latest_price.get(symbol_b, 0) > 0:
                    counterpart.mid_price_at_signal = latest_price[symbol_b]
                    counterpart.timestamp = trade_ts
                    signals.append(counterpart)
                    cp_order = _signal_to_order(counterpart)
                    cp_fill = simulator.simulate_fill(
                        order=cp_order,
                        mid_price=latest_price[symbol_b],
                        spread=latest_price[symbol_b] * 0.0001,
                    )
                    cp_fill.timestamp = trade_ts
                    fills.append(cp_fill)

        return signals, fills
