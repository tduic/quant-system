"""Strategy evaluator — runs a strategy over a trade sequence and returns metrics.

This is the adapter that connects the abstract StrategyEvaluator protocol
(used by walk-forward, param sensitivity, etc.) to the actual Alpha Engine
strategies (MeanReversion, PairsTradingStrategy).

It creates a strategy instance, feeds trades through it, simulates fills
at the trade price (with configurable fee/slippage), and computes
performance metrics from the resulting PnL stream.

This module has NO external dependencies (no Kafka, no DB, no Redis) —
it operates entirely on in-memory trade lists, making it suitable for
fast parameter sweeps.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight fill simulation (no Kafka/execution service needed)
# ---------------------------------------------------------------------------


@dataclass
class SimulatedFill:
    """A fill produced by the evaluator's simple simulator."""

    timestamp: int = 0
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    fee: float = 0.0
    slippage_bps: float = 0.0
    strategy_id: str = ""


@dataclass
class EvaluatorConfig:
    """Configuration for the evaluator."""

    fee_rate: float = 0.006  # default Coinbase taker fee
    slippage_bps: float = 1.0  # additional slippage in basis points
    initial_equity: float = 100_000.0
    strategy_type: str = "mean_reversion"  # or "pairs_trading"
    symbol: str = "BTCUSD"
    symbol_b: str = "ETHUSD"  # for pairs trading


# ---------------------------------------------------------------------------
# Metrics computation from fills
# ---------------------------------------------------------------------------

ANNUAL_FACTOR = 365.0


def _compute_metrics_from_fills(
    fills: list[SimulatedFill],
    initial_equity: float,
    signals_emitted: int = 0,
) -> dict[str, float]:
    """Compute Sharpe, return, drawdown, etc. from a list of fills."""
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
    returns: list[float] = []
    prev_equity = initial_equity

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
            sharpe = (mean_r / std_r) * math.sqrt(ANNUAL_FACTOR)

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
# Trade dict → Trade model conversion (lightweight, no quant_core import)
# ---------------------------------------------------------------------------


@dataclass
class _LiteTrade:
    """Lightweight trade for strategy consumption without importing quant_core."""

    price: float = 0.0
    quantity: float = 0.0
    is_buyer_maker: bool = False
    timestamp_exchange: int = 0
    timestamp_ingested: int = 0
    symbol: str = ""
    trade_id: int = 0
    type: str = "trade"
    exchange: str = "coinbase"


@dataclass
class _LiteSignal:
    """Lightweight signal output."""

    signal_id: str = ""
    timestamp: int = 0
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    strength: float = 0.0
    target_quantity: float = 0.0
    mid_price_at_signal: float = 0.0
    spread_at_signal: float = 0.0
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy evaluator
# ---------------------------------------------------------------------------


class LocalStrategyEvaluator:
    """Evaluates a strategy by replaying trades through it locally.

    Compatible with the StrategyEvaluator protocol expected by
    walk_forward.run_walk_forward() and param_sensitivity.run_sensitivity().

    Usage:
        evaluator = LocalStrategyEvaluator(config=EvaluatorConfig(
            strategy_type="mean_reversion",
            symbol="BTCUSD",
        ))

        # For walk-forward / param sensitivity:
        metrics = evaluator.evaluate(trades, {"threshold_std": 2.0, "window_size": 100})

        # For cost sensitivity:
        metrics = evaluator.evaluate(trades, {"fee_rate": 0.008, "slippage_bps": 5.0})
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
        Strategy params override defaults; cost params override config.
        """
        fee_rate = params.get("fee_rate", self._config.fee_rate)
        slippage_bps = params.get("slippage_bps", self._config.slippage_bps)

        # Build strategy params (exclude cost keys)
        cost_keys = {"fee_rate", "slippage_bps", "latency_ms"}
        strategy_params = {k: v for k, v in params.items() if k not in cost_keys}

        # Create strategy and run
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
        fee_rate: float,
        slippage_bps: float,
    ) -> tuple[list[_LiteSignal], list[SimulatedFill]]:
        """Replay trades through the strategy and collect signals/fills."""
        strategy_type = self._config.strategy_type

        if strategy_type == "mean_reversion":
            return self._run_mean_reversion(trades, strategy_params, fee_rate, slippage_bps)
        if strategy_type == "pairs_trading":
            return self._run_pairs_trading(trades, strategy_params, fee_rate, slippage_bps)
        # Generic: just return empty (extensible for future strategies)
        return [], []

    def _run_mean_reversion(
        self,
        trades: list[dict],
        params: dict[str, Any],
        fee_rate: float,
        slippage_bps: float,
    ) -> tuple[list[_LiteSignal], list[SimulatedFill]]:
        """Run mean-reversion strategy over trade dicts."""
        # Strategy config
        window_size = int(params.get("window_size", 100))
        threshold_std = float(params.get("threshold_std", 2.0))
        warmup_trades = int(params.get("warmup_trades", 50))
        base_quantity = float(params.get("base_quantity", 0.001))
        cooldown_trades = int(params.get("cooldown_trades", 10))

        # Inline mean-reversion logic (avoids importing quant_core.models
        # which fails on Python 3.10 sandbox)
        prices: list[float] = []
        quantities: list[float] = []
        pv_sum = 0.0
        v_sum = 0.0

        trade_count = 0
        trades_since_signal = cooldown_trades  # start ready
        last_signal_side: str | None = None

        signals: list[_LiteSignal] = []
        fills: list[SimulatedFill] = []

        for t in trades:
            price = float(t.get("price", 0))
            qty = float(t.get("quantity", 0.001))
            ts = int(t.get("timestamp_exchange", 0))
            symbol = t.get("symbol", self._config.symbol)

            if price <= 0:
                continue

            trade_count += 1
            trades_since_signal += 1

            # Update rolling VWAP and volatility
            if len(prices) >= window_size:
                old_p = prices.pop(0)
                old_q = quantities.pop(0)
                pv_sum -= old_p * old_q
                v_sum -= old_q

            prices.append(price)
            quantities.append(qty)
            pv_sum += price * qty
            v_sum += qty

            if trade_count < warmup_trades:
                continue

            if trades_since_signal < cooldown_trades:
                continue

            # Compute VWAP
            vwap = pv_sum / v_sum if v_sum > 0 else 0.0
            if vwap == 0:
                continue

            # Compute volatility
            if len(prices) < 2:
                continue
            ret_list = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1] > 0]
            if not ret_list:
                continue
            mean_ret = sum(ret_list) / len(ret_list)
            var_ret = sum((r - mean_ret) ** 2 for r in ret_list) / len(ret_list)
            vol = var_ret**0.5
            if vol == 0:
                continue

            z_score = (price - vwap) / vol

            side = None
            strength = 0.0
            if z_score < -threshold_std:
                side = "BUY"
                strength = min(abs(z_score) / (threshold_std * 2), 1.0)
            elif z_score > threshold_std:
                side = "SELL"
                strength = min(abs(z_score) / (threshold_std * 2), 1.0)

            if side is None:
                continue

            if side == last_signal_side:
                continue

            last_signal_side = side
            trades_since_signal = 0

            sig = _LiteSignal(
                signal_id=f"sig-{trade_count}",
                timestamp=ts,
                strategy_id="mean_reversion_eval",
                symbol=symbol,
                side=side,
                strength=strength,
                target_quantity=base_quantity,
                mid_price_at_signal=price,
            )
            signals.append(sig)

            # Simulate immediate fill
            slip = price * slippage_bps / 10_000.0
            fill_price = price + slip if side == "BUY" else price - slip
            fee = base_quantity * fill_price * fee_rate

            fills.append(
                SimulatedFill(
                    timestamp=ts,
                    symbol=symbol,
                    side=side,
                    quantity=base_quantity,
                    fill_price=fill_price,
                    fee=fee,
                    slippage_bps=slippage_bps,
                    strategy_id="mean_reversion_eval",
                )
            )

        return signals, fills

    def _run_pairs_trading(
        self,
        trades: list[dict],
        params: dict[str, Any],
        fee_rate: float,
        slippage_bps: float,
    ) -> tuple[list[_LiteSignal], list[SimulatedFill]]:
        """Run pairs trading strategy over trade dicts.

        Trades must contain both symbol_a and symbol_b data, sorted by timestamp.
        """
        entry_threshold = float(params.get("entry_threshold", 2.0))
        min_correlation = float(params.get("min_correlation", 0.5))
        warmup_trades = int(params.get("warmup_trades", 30))
        cooldown_trades = int(params.get("cooldown_trades", 20))
        base_quantity = float(params.get("base_quantity", 0.001))
        window = int(params.get("window", 100))

        symbol_a = self._config.symbol
        symbol_b = self._config.symbol_b

        # Track log prices for spread z-score
        log_prices_a: list[float] = []
        log_prices_b: list[float] = []
        trade_count = 0
        trades_since_signal = cooldown_trades

        signals: list[_LiteSignal] = []
        fills: list[SimulatedFill] = []

        latest_price: dict[str, float] = {}

        for t in trades:
            sym = t.get("symbol", "")
            price = float(t.get("price", 0))
            ts = int(t.get("timestamp_exchange", 0))

            if price <= 0:
                continue

            latest_price[sym] = price

            if sym == symbol_a:
                log_prices_a.append(math.log(price))
                if len(log_prices_a) > window:
                    log_prices_a.pop(0)
            elif sym == symbol_b:
                log_prices_b.append(math.log(price))
                if len(log_prices_b) > window:
                    log_prices_b.pop(0)
            else:
                continue

            trade_count += 1
            trades_since_signal += 1

            if trade_count < warmup_trades:
                continue
            if trades_since_signal < cooldown_trades:
                continue

            n = min(len(log_prices_a), len(log_prices_b))
            if n < 20:
                continue

            # Compute correlation of log returns
            a_slice = log_prices_a[-n:]
            b_slice = log_prices_b[-n:]

            returns_a = [a_slice[i] - a_slice[i - 1] for i in range(1, len(a_slice))]
            returns_b = [b_slice[i] - b_slice[i - 1] for i in range(1, len(b_slice))]

            corr = _pearson(returns_a, returns_b)
            if corr < min_correlation:
                continue

            # Spread z-score on log price ratio
            spread = [a - b for a, b in zip(a_slice, b_slice, strict=True)]
            mean_s = sum(spread) / len(spread)
            var_s = sum((s - mean_s) ** 2 for s in spread) / len(spread)
            std_s = var_s**0.5
            if std_s == 0:
                continue

            z = (spread[-1] - mean_s) / std_s

            if abs(z) < entry_threshold:
                continue

            # z > threshold → spread is too wide → short A, long B
            # z < -threshold → spread is too narrow → long A, short B
            side_a = "SELL" if z > 0 else "BUY"
            side_b = "BUY" if z > 0 else "SELL"
            trades_since_signal = 0

            for leg_sym, leg_side in [(symbol_a, side_a), (symbol_b, side_b)]:
                p = latest_price.get(leg_sym, 0)
                if p <= 0:
                    continue

                sig = _LiteSignal(
                    signal_id=f"sig-{trade_count}-{leg_sym}",
                    timestamp=ts,
                    strategy_id="pairs_eval",
                    symbol=leg_sym,
                    side=leg_side,
                    strength=min(abs(z) / (entry_threshold * 2), 1.0),
                    target_quantity=base_quantity,
                    mid_price_at_signal=p,
                )
                signals.append(sig)

                slip = p * slippage_bps / 10_000.0
                fp = p + slip if leg_side == "BUY" else p - slip
                fee = base_quantity * fp * fee_rate

                fills.append(
                    SimulatedFill(
                        timestamp=ts,
                        symbol=leg_sym,
                        side=leg_side,
                        quantity=base_quantity,
                        fill_price=fp,
                        fee=fee,
                        slippage_bps=slippage_bps,
                        strategy_id="pairs_eval",
                    )
                )

        return signals, fills


def _pearson(x: list[float], y: list[float]) -> float:
    """Pearson correlation."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    x = x[:n]
    y = y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True)) / n
    sx = (sum((xi - mx) ** 2 for xi in x) / n) ** 0.5
    sy = (sum((yi - my) ** 2 for yi in y) / n) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)
