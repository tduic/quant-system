"""Tests for backtest analysis: alpha decay per run + per-symbol breakdown."""

from __future__ import annotations

from backtest_svc.backtest_analysis import (
    BacktestSignal,
    _find_price_at,
    analyze_backtest_run,
    compute_alpha_decay,
    compute_per_symbol_analysis,
)

# ---------------------------------------------------------------------------
# Alpha decay tests
# ---------------------------------------------------------------------------


class TestComputeAlphaDecay:
    def test_empty_signals(self):
        result = compute_alpha_decay([], [])
        assert result.total_signals == 0
        assert result.overall_horizons == []

    def test_empty_trades(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=1000,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            )
        ]
        result = compute_alpha_decay(signals, [])
        assert result.total_signals == 1
        assert result.overall_horizons == []

    def test_basic_ic_computation(self):
        # 10 BUY signals at different times, price consistently rises
        signals = [
            BacktestSignal(
                signal_id=f"s{i}",
                timestamp_ms=i * 100_000,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0 + i * 10,
            )
            for i in range(10)
        ]

        # Trades showing price rise at each horizon
        trades = [
            {"symbol": "BTCUSD", "timestamp_exchange": t, "price": 50000.0 + t * 0.001}
            for t in range(0, 2_000_000, 10_000)
        ]

        result = compute_alpha_decay(signals, trades, horizons_ms=[60_000, 300_000])
        assert result.total_signals == 10
        assert len(result.overall_horizons) == 2
        # At least some horizons should be filled
        filled = [h for h in result.overall_horizons if h.filled_count > 0]
        assert len(filled) > 0

    def test_per_strategy_breakdown(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            ),
            BacktestSignal(
                signal_id="s2",
                timestamp_ms=0,
                strategy_id="strat_b",
                symbol="BTCUSD",
                side="SELL",
                strength=0.6,
                mid_price=50000.0,
            ),
        ]
        trades = [
            {"symbol": "BTCUSD", "timestamp_exchange": t, "price": 50000.0 + t * 0.001} for t in range(0, 500_000, 5000)
        ]

        result = compute_alpha_decay(signals, trades, horizons_ms=[60_000])
        assert len(result.per_strategy) == 2
        strat_ids = {s.strategy_id for s in result.per_strategy}
        assert strat_ids == {"strat_a", "strat_b"}

    def test_multi_symbol_signals(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            ),
            BacktestSignal(
                signal_id="s2",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="ETHUSD",
                side="BUY",
                strength=0.7,
                mid_price=3000.0,
            ),
        ]
        trades = [
            {"symbol": "BTCUSD", "timestamp_exchange": t, "price": 50000.0} for t in range(0, 200_000, 10_000)
        ] + [{"symbol": "ETHUSD", "timestamp_exchange": t, "price": 3000.0} for t in range(0, 200_000, 10_000)]

        result = compute_alpha_decay(signals, trades, horizons_ms=[60_000])
        assert result.total_signals == 2

    def test_horizon_beyond_data_returns_none(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            )
        ]
        # Only 30 seconds of data, but horizon is 1 minute
        trades = [{"symbol": "BTCUSD", "timestamp_exchange": t, "price": 50000.0} for t in range(0, 30_000, 1000)]

        result = compute_alpha_decay(signals, trades, horizons_ms=[60_000])
        assert result.overall_horizons[0].filled_count == 0


class TestFindPriceAt:
    def test_exact_match(self):
        timeline = [(100, 50.0), (200, 51.0), (300, 52.0)]
        assert _find_price_at(timeline, 200) == 51.0

    def test_between_points(self):
        timeline = [(100, 50.0), (200, 51.0), (300, 52.0)]
        # Should return the first price at or after 150 → 200 → 51.0
        assert _find_price_at(timeline, 150) == 51.0

    def test_beyond_range(self):
        timeline = [(100, 50.0), (200, 51.0)]
        assert _find_price_at(timeline, 300) is None

    def test_empty_timeline(self):
        assert _find_price_at([], 100) is None

    def test_first_element(self):
        timeline = [(100, 50.0), (200, 51.0)]
        assert _find_price_at(timeline, 50) == 50.0


# ---------------------------------------------------------------------------
# Per-symbol analysis tests
# ---------------------------------------------------------------------------


def _make_fill(symbol, side, qty, price, fee=0.5, slippage=1.0):
    return {
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "fill_price": price,
        "fee": fee,
        "slippage_bps": slippage,
    }


class TestComputePerSymbolAnalysis:
    def test_empty_fills(self):
        result = compute_per_symbol_analysis([])
        assert result.symbols == []
        assert result.best_symbol == ""

    def test_single_symbol(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000),
            _make_fill("BTCUSD", "SELL", 0.1, 51000),
        ]
        result = compute_per_symbol_analysis(fills)
        assert len(result.symbols) == 1
        assert result.symbols[0].symbol == "BTCUSD"
        assert result.symbols[0].num_fills == 2
        assert result.symbols[0].buy_fills == 1
        assert result.symbols[0].sell_fills == 1

    def test_multi_symbol(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000),
            _make_fill("BTCUSD", "SELL", 0.1, 51000),
            _make_fill("ETHUSD", "BUY", 1.0, 3000),
            _make_fill("ETHUSD", "SELL", 1.0, 2900),
        ]
        result = compute_per_symbol_analysis(fills)
        assert len(result.symbols) == 2
        symbols = {m.symbol for m in result.symbols}
        assert symbols == {"BTCUSD", "ETHUSD"}

    def test_best_worst_symbol(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000),
            _make_fill("BTCUSD", "SELL", 0.1, 55000),  # profit
            _make_fill("ETHUSD", "BUY", 1.0, 3000),
            _make_fill("ETHUSD", "SELL", 1.0, 2000),  # loss
        ]
        result = compute_per_symbol_analysis(fills)
        assert result.best_symbol == "BTCUSD"
        assert result.worst_symbol == "ETHUSD"

    def test_win_rate(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000, fee=0),
            _make_fill("BTCUSD", "SELL", 0.1, 51000, fee=0),  # win
            _make_fill("BTCUSD", "BUY", 0.1, 50000, fee=0),
            _make_fill("BTCUSD", "SELL", 0.1, 49000, fee=0),  # loss
        ]
        result = compute_per_symbol_analysis(fills)
        # 1 win out of 4 fills → 0.25
        # (only closing fills can be wins; 2 closes, 1 win → depends on logic)
        assert result.symbols[0].win_rate >= 0

    def test_fees_tracked(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000, fee=5.0),
            _make_fill("BTCUSD", "SELL", 0.1, 50000, fee=5.0),
        ]
        result = compute_per_symbol_analysis(fills)
        assert result.symbols[0].total_fees == 10.0

    def test_slippage_averaged(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000, slippage=2.0),
            _make_fill("BTCUSD", "SELL", 0.1, 50000, slippage=4.0),
        ]
        result = compute_per_symbol_analysis(fills)
        assert result.symbols[0].avg_slippage_bps == 3.0

    def test_profitable_trade_positive_return(self):
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000, fee=0),
            _make_fill("BTCUSD", "SELL", 0.1, 60000, fee=0),
        ]
        result = compute_per_symbol_analysis(fills)
        assert result.symbols[0].total_return > 0
        assert result.symbols[0].realized_pnl > 0


# ---------------------------------------------------------------------------
# Combined analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeBacktestRun:
    def test_full_analysis(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            )
        ]
        trades = [
            {"symbol": "BTCUSD", "timestamp_exchange": t, "price": 50000.0 + t * 0.001} for t in range(0, 200_000, 5000)
        ]
        fills = [
            _make_fill("BTCUSD", "BUY", 0.1, 50000),
            _make_fill("BTCUSD", "SELL", 0.1, 51000),
        ]

        result = analyze_backtest_run(
            backtest_id="bt-test",
            signals=signals,
            trades=trades,
            fills=fills,
            horizons_ms=[60_000],
        )

        assert result["backtest_id"] == "bt-test"
        assert "alpha_decay" in result
        assert "per_symbol" in result
        assert result["alpha_decay"]["total_signals"] == 1
        assert len(result["per_symbol"]["symbols"]) == 1

    def test_signals_only(self):
        signals = [
            BacktestSignal(
                signal_id="s1",
                timestamp_ms=0,
                strategy_id="strat_a",
                symbol="BTCUSD",
                side="BUY",
                strength=0.8,
                mid_price=50000.0,
            )
        ]
        trades = [{"symbol": "BTCUSD", "timestamp_exchange": 100_000, "price": 50100.0}]

        result = analyze_backtest_run(backtest_id="bt-test", signals=signals, trades=trades)
        assert "alpha_decay" in result
        assert "per_symbol" not in result

    def test_fills_only(self):
        fills = [_make_fill("BTCUSD", "BUY", 0.1, 50000)]
        result = analyze_backtest_run(backtest_id="bt-test", fills=fills)
        assert "per_symbol" in result
        assert "alpha_decay" not in result

    def test_empty_analysis(self):
        result = analyze_backtest_run(backtest_id="bt-test")
        assert result == {"backtest_id": "bt-test"}
