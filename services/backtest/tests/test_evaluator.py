"""Tests for the LocalStrategyEvaluator and metrics computation."""

from __future__ import annotations

from backtest_svc.evaluator import (
    EvaluatorConfig,
    LocalStrategyEvaluator,
    _compute_metrics_from_fills,
)
from quant_core.models import Fill

# ---------------------------------------------------------------------------
# _compute_metrics_from_fills tests
# ---------------------------------------------------------------------------


class TestComputeMetricsFromFills:
    def test_empty_fills(self):
        result = _compute_metrics_from_fills([], 100_000.0)
        assert result["sharpe"] == 0.0
        assert result["total_return"] == 0.0
        assert result["max_drawdown"] == 0.0
        assert result["num_trades"] == 0

    def test_single_buy(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=50000.0,
                fee=30.0,
                slippage_bps=1.0,
                strategy_id="test",
            )
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        assert result["num_trades"] == 1
        assert result["total_fees"] == 30.0
        # Only opened position, no closing — realized PnL is just the fee
        assert result["realized_pnl"] == -30.0 - (0.1 * 50000.0 * 1.0 / 10_000.0)

    def test_round_trip_profit(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=50000.0,
                fee=0.0,
                slippage_bps=0.0,
                strategy_id="test",
            ),
            Fill(
                timestamp=2000,
                symbol="BTCUSD",
                side="SELL",
                quantity=0.1,
                fill_price=51000.0,
                fee=0.0,
                slippage_bps=0.0,
                strategy_id="test",
            ),
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        assert result["num_trades"] == 2
        assert result["total_return"] > 0
        # 0.1 * (51000 - 50000) = 100 profit
        assert abs(result["realized_pnl"] - 100.0) < 0.01

    def test_round_trip_loss(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=50000.0,
                fee=0.0,
                slippage_bps=0.0,
                strategy_id="test",
            ),
            Fill(
                timestamp=2000,
                symbol="BTCUSD",
                side="SELL",
                quantity=0.1,
                fill_price=49000.0,
                fee=0.0,
                slippage_bps=0.0,
                strategy_id="test",
            ),
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        assert result["total_return"] < 0
        # 0.1 * (49000 - 50000) = -100 loss
        assert abs(result["realized_pnl"] - (-100.0)) < 0.01

    def test_fees_reduce_pnl(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=50000.0,
                fee=50.0,
                slippage_bps=0.0,
            ),
            Fill(
                timestamp=2000,
                symbol="BTCUSD",
                side="SELL",
                quantity=0.1,
                fill_price=51000.0,
                fee=50.0,
                slippage_bps=0.0,
            ),
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        # Gross PnL = 100, but 50 fee on open + (100 - 50) on close = 0 net
        assert result["total_fees"] == 100.0
        assert result["realized_pnl"] < 100.0

    def test_drawdown_tracked(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=50000.0,
                fee=0.0,
                slippage_bps=0.0,
            ),
            Fill(
                timestamp=2000,
                symbol="BTCUSD",
                side="SELL",
                quantity=0.1,
                fill_price=49000.0,
                fee=0.0,
                slippage_bps=0.0,
            ),
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        assert result["max_drawdown"] > 0

    def test_signals_count_passthrough(self):
        result = _compute_metrics_from_fills([], 100_000.0, signals_emitted=5)
        assert result["num_signals"] == 5

    def test_short_round_trip(self):
        fills = [
            Fill(
                timestamp=1000,
                symbol="BTCUSD",
                side="SELL",
                quantity=0.1,
                fill_price=50000.0,
                fee=0.0,
                slippage_bps=0.0,
            ),
            Fill(
                timestamp=2000,
                symbol="BTCUSD",
                side="BUY",
                quantity=0.1,
                fill_price=49000.0,
                fee=0.0,
                slippage_bps=0.0,
            ),
        ]
        result = _compute_metrics_from_fills(fills, 100_000.0)
        # Short at 50k, cover at 49k → profit 100
        assert abs(result["realized_pnl"] - 100.0) < 0.01


# ---------------------------------------------------------------------------
# LocalStrategyEvaluator tests — mean reversion
# ---------------------------------------------------------------------------


def _make_trending_trades(
    symbol: str = "BTCUSD",
    n: int = 300,
    start_price: float = 50000.0,
    drift: float = 0.5,
) -> list[dict]:
    """Generate trades with a consistent upward drift for signal generation."""
    import random

    rng = random.Random(123)
    price = start_price
    trades = []
    for i in range(n):
        # Mean-reverting random walk with upward drift
        noise = rng.gauss(0, 30)
        # Add occasional large moves to trigger signals
        if i % 50 == 25:
            noise += 200 * (1 if i % 100 == 25 else -1)
        price += drift + noise - (price - start_price) * 0.002
        price = max(price, 100)
        trades.append(
            {
                "symbol": symbol,
                "price": round(price, 2),
                "quantity": round(rng.uniform(0.001, 0.05), 4),
                "timestamp_exchange": 1000000 + i * 1000,
                "is_buyer_maker": rng.random() > 0.5,
            }
        )
    return trades


class TestLocalStrategyEvaluatorMeanReversion:
    def test_basic_evaluate(self):
        config = EvaluatorConfig(strategy_type="mean_reversion", symbol="BTCUSD")
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_trending_trades(n=300)
        metrics = evaluator.evaluate(trades, {"threshold_std": 2.0, "window_size": 50})
        assert "sharpe" in metrics
        assert "total_return" in metrics
        assert "max_drawdown" in metrics
        assert "num_trades" in metrics

    def test_warmup_period_respected(self):
        config = EvaluatorConfig(strategy_type="mean_reversion")
        evaluator = LocalStrategyEvaluator(config)
        # Only 10 trades — far below warmup
        trades = _make_trending_trades(n=10)
        metrics = evaluator.evaluate(trades, {"warmup_trades": 50})
        assert metrics["num_trades"] == 0

    def test_cost_params_override(self):
        config = EvaluatorConfig(strategy_type="mean_reversion", fee_rate=0.006, slippage_bps=1.0)
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_trending_trades(n=500)

        # Higher costs should reduce returns
        metrics_low_cost = evaluator.evaluate(trades, {"fee_rate": 0.001, "slippage_bps": 0.5})
        metrics_high_cost = evaluator.evaluate(trades, {"fee_rate": 0.02, "slippage_bps": 20.0})

        # Both should run; high cost should have worse PnL
        if metrics_low_cost["num_trades"] > 0 and metrics_high_cost["num_trades"] > 0:
            assert metrics_high_cost["total_costs"] >= metrics_low_cost["total_costs"]

    def test_threshold_affects_signal_count(self):
        config = EvaluatorConfig(strategy_type="mean_reversion")
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_trending_trades(n=500)

        # Low threshold → more signals; high threshold → fewer
        m_low = evaluator.evaluate(trades, {"threshold_std": 0.5, "window_size": 50})
        m_high = evaluator.evaluate(trades, {"threshold_std": 5.0, "window_size": 50})
        assert m_low["num_signals"] >= m_high["num_signals"]

    def test_empty_trades(self):
        config = EvaluatorConfig(strategy_type="mean_reversion")
        evaluator = LocalStrategyEvaluator(config)
        metrics = evaluator.evaluate([], {})
        assert metrics["num_trades"] == 0
        assert metrics["sharpe"] == 0.0

    def test_zero_price_skipped(self):
        config = EvaluatorConfig(strategy_type="mean_reversion")
        evaluator = LocalStrategyEvaluator(config)
        trades = [{"symbol": "BTCUSD", "price": 0, "quantity": 0.01, "timestamp_exchange": i} for i in range(100)]
        metrics = evaluator.evaluate(trades, {})
        assert metrics["num_trades"] == 0

    def test_cooldown_reduces_signals(self):
        config = EvaluatorConfig(strategy_type="mean_reversion")
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_trending_trades(n=500)

        m_short_cd = evaluator.evaluate(trades, {"threshold_std": 1.0, "cooldown_trades": 1, "window_size": 30})
        m_long_cd = evaluator.evaluate(trades, {"threshold_std": 1.0, "cooldown_trades": 100, "window_size": 30})
        assert m_short_cd["num_signals"] >= m_long_cd["num_signals"]


# ---------------------------------------------------------------------------
# LocalStrategyEvaluator tests — pairs trading
# ---------------------------------------------------------------------------


def _make_pair_trades(
    symbol_a: str = "BTCUSD",
    symbol_b: str = "ETHUSD",
    n: int = 200,
) -> list[dict]:
    """Generate correlated pair trades interleaved by timestamp."""
    import random

    rng = random.Random(456)
    price_a = 50000.0
    price_b = 3000.0
    trades = []
    for i in range(n):
        # Correlated moves
        shock = rng.gauss(0, 50)
        price_a += shock + rng.gauss(0, 10)
        price_b += shock * 0.06 + rng.gauss(0, 1)  # ~60:1 ratio
        price_a = max(price_a, 100)
        price_b = max(price_b, 10)
        ts = 1000000 + i * 500

        trades.append(
            {
                "symbol": symbol_a,
                "price": round(price_a, 2),
                "quantity": 0.01,
                "timestamp_exchange": ts,
            }
        )
        trades.append(
            {
                "symbol": symbol_b,
                "price": round(price_b, 2),
                "quantity": 0.1,
                "timestamp_exchange": ts + 100,
            }
        )
    # Sort by timestamp
    trades.sort(key=lambda t: t["timestamp_exchange"])
    return trades


class TestLocalStrategyEvaluatorPairs:
    def test_basic_pairs_evaluate(self):
        config = EvaluatorConfig(
            strategy_type="pairs_trading",
            symbol="BTCUSD",
            symbol_b="ETHUSD",
        )
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_pair_trades(n=300)
        metrics = evaluator.evaluate(trades, {"entry_threshold": 2.0, "min_correlation": 0.3})
        assert "sharpe" in metrics
        assert "total_return" in metrics

    def test_pairs_empty_trades(self):
        config = EvaluatorConfig(strategy_type="pairs_trading")
        evaluator = LocalStrategyEvaluator(config)
        metrics = evaluator.evaluate([], {})
        assert metrics["num_trades"] == 0

    def test_pairs_warmup(self):
        config = EvaluatorConfig(strategy_type="pairs_trading")
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_pair_trades(n=5)
        metrics = evaluator.evaluate(trades, {"warmup_trades": 100})
        assert metrics["num_trades"] == 0

    def test_pairs_high_correlation_requirement(self):
        config = EvaluatorConfig(
            strategy_type="pairs_trading",
            symbol="BTCUSD",
            symbol_b="ETHUSD",
        )
        evaluator = LocalStrategyEvaluator(config)
        trades = _make_pair_trades(n=300)

        # Very high min_correlation should produce fewer or no signals
        m_easy = evaluator.evaluate(trades, {"min_correlation": 0.1, "entry_threshold": 1.5})
        m_hard = evaluator.evaluate(trades, {"min_correlation": 0.99, "entry_threshold": 1.5})
        assert m_easy["num_signals"] >= m_hard["num_signals"]


# ---------------------------------------------------------------------------
# Unknown strategy type
# ---------------------------------------------------------------------------


class TestUnknownStrategy:
    def test_unknown_returns_empty(self):
        config = EvaluatorConfig(strategy_type="unknown_strategy")
        evaluator = LocalStrategyEvaluator(config)
        metrics = evaluator.evaluate(_make_trending_trades(n=100), {})
        assert metrics["num_trades"] == 0
        assert metrics["sharpe"] == 0.0


# ---------------------------------------------------------------------------
# EvaluatorConfig defaults
# ---------------------------------------------------------------------------


class TestEvaluatorConfig:
    def test_defaults(self):
        cfg = EvaluatorConfig()
        assert cfg.fee_rate is None  # None → tiered fee model via FillSimulator
        assert cfg.slippage_bps == 1.0
        assert cfg.initial_equity == 100_000.0
        assert cfg.strategy_type == "mean_reversion"

    def test_custom(self):
        cfg = EvaluatorConfig(
            fee_rate=0.01,
            slippage_bps=5.0,
            initial_equity=50_000.0,
            strategy_type="pairs_trading",
            symbol="ETHUSD",
            symbol_b="SOLUSD",
        )
        assert cfg.fee_rate == 0.01
        assert cfg.symbol_b == "SOLUSD"
